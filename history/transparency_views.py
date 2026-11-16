"""
Trazo Consumer Transparency API Views
Provides transparency-first data for QR scanning experience
Eliminates competitive carbon ranking to solve farmer incentive problems

Following Trazo's main goal: Authentic transparency leadership
"""

import logging
import re

from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.gzip import gzip_page

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from carbon.services.calculator_service import CarbonCalculatorService
from certifications.constants import CONSUMER_LISTED_STATUSES
from common.location import city_state_label
from common.specimen import SPECIMEN_BODY, SPECIMEN_TITLE, is_specimen

from .models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    PestManagementEvent,
    Production,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from .serializers import PublicHistorySerializer
from .services.privacy import establishment_supplier_names, public_free_text, redact_supplier_names
from .services.transparency_calculator import TransparencyCalculator
from .services.transparency_response_formatter import TransparencyResponseFormatter

logger = logging.getLogger(__name__)


# gzip — see the note on HistoryViewSet.public_history. Same anonymous consumer surface,
# same 258-event measurement (179.7 KB -> 6.1 KB), same reasoning for scoping compression
# to unauthenticated endpoints instead of enabling GZipMiddleware globally.
@gzip_page
@api_view(["GET"])
@permission_classes([AllowAny])
def production_transparency_detail(request, production_public_id=None):
    """
    Consumer-facing transparency endpoint for QR scanning

    Returns documentation counts and carbon data WITHOUT competitive rankings
    This solves the farmer gaming incentive problem by rewarding honesty over competition

    Accepts UUID (production_public_id) only.
    """
    try:
        # Build lookup filter: UUID only (prevents integer enumeration)
        if production_public_id is None:
            return Response({"error": "Production identifier required"}, status=status.HTTP_400_BAD_REQUEST)
        lookup_kwargs = {"public_id": production_public_id}

        # Get production with related data (optimized query with prefetch for all event types and carbon data)
        # This eliminates N+1 queries by prefetching all 8 event types with their albums and images
        # OPTIMIZATION (2025-12-12): Also prefetch CarbonEntry to support carbon data lookups
        from carbon.models import CarbonEntry

        base_qs = Production.objects.select_related(
            "product", "parcel__establishment__company", "parcel__establishment"
        ).prefetch_related(
            # Prefetch all 8 event types with albums and images to avoid N+1 queries
            Prefetch(
                "history_weatherevent_events",
                queryset=WeatherEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_chemicalevent_events",
                queryset=ChemicalEvent.objects.select_related("album", "omri_product").prefetch_related(
                    "album__images"
                ),
            ),
            Prefetch(
                "history_productionevent_events",
                queryset=ProductionEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_generalevent_events",
                queryset=GeneralEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_equipmentevent_events",
                queryset=EquipmentEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_soilmanagementevent_events",
                queryset=SoilManagementEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_pestmanagementevent_events",
                queryset=PestManagementEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_businessevent_events",
                queryset=BusinessEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            # OPTIMIZATION (2025-12-12): Prefetch all CarbonEntry records for this production
            # This eliminates separate queries when _get_event_carbon_data() is called
            Prefetch("carbonentry_set", queryset=CarbonEntry.objects.all().order_by("-created_at")),
        )

        # Authenticated owners can view their own unpublished productions (farmer dashboard)
        # Anonymous/consumer users can only see published productions (QR scanning)
        #
        # `public_view=1` (2026-10-08) drops the owner exemption: the consumer page sends it so a
        # grower who unpublishes a lot gets the same 404 a shopper gets. The auth cookies are
        # scoped to `.trazo.io`, so they reach `consumer.trazo.io` too; without this the owner kept
        # seeing the full page after switching Public off and concluded the toggle was broken.
        # The dashboard calls this endpoint without the flag and keeps its preview.
        #
        # `owns_it` is the FACT; `is_owner` is the exemption. The flag turns off only the
        # exemption: an owner opening their own buyer link must still not be logged as the
        # buyer's open below.
        public_view = request.query_params.get("public_view") == "1"
        owns_it = False
        if request.user.is_authenticated:
            try:
                h = Production.objects.select_related("parcel__establishment__company").get(**lookup_kwargs)
                if h.parcel and h.parcel.establishment and h.parcel.establishment.company:
                    owns_it = request.user.companies.filter(id=h.parcel.establishment.company_id).exists()
            except Production.DoesNotExist:
                pass
        is_owner = owns_it and not public_view

        # Buyer review token (2026-08-25): mirrors public_history — an active
        # buyer-audience link opens this establishment's unpublished productions.
        # Same payload either way; the token only changes which productions resolve.
        buyer_link = None
        if not is_owner:
            from certifications.models import CertifierAccessLink

            buyer_link = CertifierAccessLink.resolve_buyer_token(request.query_params.get("review_token"))

        if is_owner:
            history = get_object_or_404(base_qs, **lookup_kwargs)
        elif buyer_link is not None:
            history = get_object_or_404(
                base_qs.filter(Q(published=True) | Q(parcel__establishment=buyer_link.establishment)),
                **lookup_kwargs,
            )
            # Log the open to the LINK, not as a consumer scan: this endpoint is the
            # one the consumer page actually fetches, so without this row the farmer's
            # "did my buyer look?" log only covered public_history (which the page
            # does not call). Logged only when the token is what granted access —
            # a published production of some other farm resolving alongside a valid
            # token is ordinary public traffic, not a buyer open. Nor is the grower opening
            # their own link under `public_view`.
            if not owns_it and history.parcel and history.parcel.establishment_id == buyer_link.establishment_id:
                from certifications.models import CertifierAccessLog
                from certifications.views import _client_ip

                CertifierAccessLog.objects.create(
                    link=buyer_link,
                    action="production",
                    ip_address=_client_ip(request),
                    user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
                )
        else:
            history = get_object_or_404(base_qs, published=True, **lookup_kwargs)

        # Initialize services
        transparency_calculator = TransparencyCalculator()
        carbon_service = CarbonCalculatorService()

        # The calculator is kept ONLY as the source of FACTS (event count per category, photo
        # counts, farming approach). Every graded output it also produces — the percentage,
        # `detailed_view`, the "verification" verdict, the ≥90 % "achievement" — left this
        # endpoint for every caller on 2026-09-05: no producer surface rendered them, and the
        # anonymous gate below had always stripped them. Cheap since the same day: it reads the
        # events prefetched above instead of re-querying per model and per event.
        transparency_data = transparency_calculator.calculate_transparency_score(history)

        # Get carbon data (EXISTING - but without competitive ranking)
        try:
            carbon_data = carbon_service.calculate_production_carbon(history.id)
        except Exception as e:
            logger.warning(f"Carbon calculation failed for history {history.id}: {str(e)}")
            # Don't let carbon calculation errors block transparency data
            carbon_data = {}

        # Build farm information
        establishment = history.parcel.establishment if history.parcel else None
        farm_info = {
            "name": establishment.name if establishment else "Farm",
            "location": city_state_label(establishment),
            "total_area": establishment.total_acreage if establishment else None,  # FIX: Use correct field name
            "country": establishment.country if establishment else None,
        }

        # Certification data for consumer badges + FTC-compliant organic claim gate.
        # The organic_claim block is the regulatory single source of truth for what
        # the QR page may say about organic status (7 CFR 205.300, 16 CFR 260.6(d)).
        # See certifications/services/consumer_claim_validator.py.
        certification_data = []
        organic_claim = None
        if establishment:
            try:
                from certifications.models import Certification
                from certifications.serializers import ConsumerCertificationSerializer
                from certifications.services.consumer_claim_validator import (
                    ConsumerClaimValidator,
                    filter_certifications_for_consumer,
                )

                active_certs = list(
                    Certification.objects.filter(
                        establishment=establishment,
                        verification_status__in=CONSUMER_LISTED_STATUSES,
                    ).exclude(
                        expiry_date__lt=timezone.now().date(),
                    )
                )
                # Strip any unverified USDA Organic cert so it never surfaces as a
                # badge — the organic_claim block below is the only gate for
                # organic language on the consumer page.
                active_certs = filter_certifications_for_consumer(active_certs)
                certification_data = ConsumerCertificationSerializer(active_certs, many=True).data

                validator = ConsumerClaimValidator()
                organic_claim = validator.validate(history).to_dict()

                # Phase 3 — lot-level gate. The farm-level claim above answers
                # "may this OPERATION be called organic"; this resolves whether
                # THIS lot may carry it (prohibited inputs, cert validity at
                # harvest, crop scope — 7 CFR 205.105/205.300). Downgrade-only.
                from history.services.claim_resolver import (
                    build_organic_claim_evidence,
                    resolve_lot_organic_eligibility,
                )

                active_organic_cert = (
                    validator._get_active_usda_organic_cert(establishment)
                    if organic_claim.get("status") == "certified_organic"
                    else None
                )
                lot_eligibility = resolve_lot_organic_eligibility(history, active_organic_cert)
                organic_claim["lot_eligibility"] = lot_eligibility.to_dict()
                organic_claim["evidence"] = build_organic_claim_evidence(organic_claim, lot_eligibility)
                if lot_eligibility.eligible is False:
                    # Server-side belt: the page must not represent this lot as
                    # organic regardless of what the frontend renders.
                    organic_claim["can_display_organic"] = False
                    organic_claim["display_label"] = lot_eligibility.display_label
                    organic_claim["disclaimer"] = (
                        "The farm holds USDA Organic certification, but this specific lot "
                        "is not represented as organic. " + lot_eligibility.detail
                    )
            except Exception as e:
                logger.warning(f"Failed to load certification/organic-claim data: {e}")

        # Organic story summary — aggregates existing data for consumer display
        # Uses already-prefetched ChemicalEvents, zero extra DB queries
        organic_summary = _build_organic_summary(history, certification_data, establishment, organic_claim)

        # Documented-practices summary — the consumer "real vs. fake organic"
        # differentiator (GTM-v3). Surfaces FACTS the farmer logged (integrated grazing,
        # cover crops, on-farm compost) so a practice-based regenerative grower stands out
        # from an input-substitution "organic" neighbor. Facts only — NO grade, NO self-label,
        # NO regenerative badge (transparency-first.md / EU ECGT). Uses prefetched soil events.
        practice_summary = _build_practice_summary(history)

        # Product information
        product_info = {
            "name": history.product.name if history.product else "Farm Product",
            "production_name": history.name or f"Production {history.public_id}",
            "start_date": history.start_date.isoformat() if history.start_date else None,
            "end_date": history.finish_date.isoformat() if history.finish_date else None,
        }

        # NOTE: Scan tracking is handled by the public_history action in HistoryViewSet
        # which includes geolocation and notifications. Removed duplicate tracking here
        # to prevent inflated scan counts when both endpoints are called.

        # Use standardized transparency response formatter
        formatter = TransparencyResponseFormatter()

        # Prepare data for formatter
        # Recordkeeping review F-02 (2026-10-07): the public figures count only entries with a
        # recorded basis (`recorded_*` from the calculator); `area_estimate` and
        # `no_factor_applied` rows stay on the farmer's dashboard total and off this payload.
        # `usda_factors_used: True` and `calculation_method: "USDA_EPA_factors"` were a blanket
        # attribution the specimen's own rows contradicted (`usda_factors_based` False on 162
        # of 417); factor sources are per input class, stated on each factor.
        recorded_per_kg = carbon_data.get("recorded_co2_kg_per_kg", carbon_data.get("gross_co2_kg_per_kg", 0))
        carbon_data_formatted = {
            "total_co2_kg_per_kg": recorded_per_kg,
            "gross_co2_kg_per_kg": recorded_per_kg,
            "total_emissions": carbon_data.get("recorded_emissions", carbon_data.get("total_emissions", 0)),
            "total_offsets": carbon_data.get("total_offsets", 0),
            # Net on the same basis as the gross figure beside it (never a consumer field).
            "net_footprint": (
                float(carbon_data.get("recorded_emissions", carbon_data.get("total_emissions", 0)) or 0)
                - float(carbon_data.get("total_offsets", 0) or 0)
            ),
        }

        # Blockchain is no longer a CONSUMER-facing claim (removed 2026-08-03). What the chain
        # can honestly support — "this record is unchanged since it was sealed" — does not
        # answer a shopper's question, and a badge invites the "verified" reading compliance.md
        # forbids (FTC 16 CFR 260.6; EU ECGT 2024/825, live 2026-09-27). The hash is still
        # written and still appears in the certifier packet as an integrity line.
        # `verified` is hard-coded False rather than dropped so an older client that still
        # reads the key cannot render a badge from a stale truthy value.
        blockchain_verification_data = {"verified": False, "transaction_hash": ""}

        # Get standardized response
        response_data = formatter.format_qr_response(
            production=history,
            carbon_data=carbon_data_formatted,
            blockchain_verification=blockchain_verification_data,
        )

        # Remove formatter fields that duplicate the view additions below
        for key in [
            "farm_context",
            "environmental_impact_description",
            "data_sources",
            "response_format",
            "timestamp",
        ]:
            response_data.pop(key, None)

        # Add timeline events with album data (same as producer page gets)
        # This ensures photos are available on consumer page
        #
        # `force_public_view` disables the owner exemption in PublicHistorySerializer. This
        # endpoint IS the consumer product page, so it must render identically for everyone —
        # a grower checking their own QR link previously received the unstripped payload
        # (REI/PHI/applicator/EPA) and could not tell that shoppers see something different.
        public_history_serializer = PublicHistorySerializer(
            history, context={"request": request, "force_public_view": True}
        )
        public_history_data = public_history_serializer.data

        # `isEpaFactorsBased` left the payload on 2026-10-07 (recordkeeping review F-02): a single
        # boolean over every carbon row was the blanket "EPA/USDA" attribution compliance.md
        # forbids, and no consumer surface read it. Factor sources are stated per factor.

        # NOTE: the "proof_points" object (a forward-compatible fact-count successor to the
        # transparency %) was built here and returned but consumed by ZERO frontend code — the
        # consumer page already surfaces every one of those facts directly (trust pillars =
        # practices/photos/certs, the "How It Was Grown" counts, the certification card, and the
        # blockchain status). It was dead, redundant payload weight and has been removed (2026-06
        # audit P2-3). Re-introduce it only alongside a UI that actually renders it.

        # Add progressive loading structure for backward compatibility
        # Every supplier this operation has recorded, for redacting the farm's own free
        # text below. Four cheap reads, once per payload.
        _supplier_names = establishment_supplier_names(establishment)
        response_data.update(
            {
                # IMMEDIATE LOAD. `transparency_score` (percentage + message) left this block for
                # every caller on 2026-09-05; the key stays as an empty object for wire compatibility.
                "quick_view": {},
                # STANDARD LOAD (10 seconds) - Core transparency details: FACTS only. The authored
                # baseline (`expected_events`) and the grade built on it (`completeness_score`) are
                # no longer constructed for anyone; per-category grades are stripped below.
                "standard_view": {
                    "transparency_details": {
                        "actual_events": transparency_data["actual_event_count"],
                        "farming_approach": transparency_data["farming_approach"],
                        "category_breakdown": transparency_data.get("category_breakdown", {}),
                    },
                    "certifications": certification_data,
                    "organic_claim": organic_claim,  # FTC 16 CFR 260.6(d) gate
                    "organic_summary": organic_summary,
                    "practice_summary": practice_summary,  # documented facts (grazing/cover/compost)
                },
                # Consumer blockchain badge removed 2026-08-03 — see the note above. Key kept
                # with a falsy payload so an un-upgraded client degrades to "no badge".
                "blockchain_verification": {"verified": False, "transaction_hash": ""},
                # Basis disclosure for what this payload actually contains.
                #
                # 🔴 2026-08-30 — this block used to describe a SCORE. `description` read
                # "Transparency score based on documented agricultural events" and
                # `scoring_method` read "Weighted category completeness across 7 event
                # categories", on a payload the 2026-08-11 gate strips every graded number
                # out of. So the one thing the consumer surface still said about the score was
                # how it is computed: the machinery survived the metric it belonged to.
                #
                # That is the rule stated at the claim-safety gate below, failing on its own
                # terms — "PUBLISH facts about the FARM. Never publish Trazo's authored
                # BASELINE, nor the scoring machinery that applies it." A weighting scheme
                # across seven categories is the machinery exactly.
                #
                # What stays is what substantiates the content the shopper is actually shown:
                # who the records came from, whether anyone independent checked them, and the
                # scope of the carbon figures. `data_source` is the required 16 CFR 260.6(d)
                # basis disclosure and is the most important line in the block.
                "methodology": {
                    "description": "Farming activities documented by the producer for this lot",
                    "data_source": "Farmer-reported data, not independently audited",
                    # Recordkeeping review F-02: "Direct operational emissions only (EPA/USDA-sourced
                    # factors)" was both phrases compliance.md lists as unsafe. The scope is what
                    # the page already says, with sources per input class.
                    "carbon_scope": (
                        "The operation's own fuel and electricity, plus the manufacturing of the "
                        "fertilizer and crop-protection products it buys; not a full life-cycle "
                        "footprint. Fuel and electricity factors are EPA-published; phosphorus and "
                        "potassium are Trazo estimates; each factor states its own source. Entries "
                        "with no recorded basis are not counted."
                    ),
                    "version": "2.1",
                    "last_updated": "2026-08-30",
                },
                # Metadata
                "api_version": "2.0",
                "response_timestamp": timezone.now().isoformat(),
                # Additional fields for frontend compatibility with ProductDetail.tsx
                "farmer": {
                    # 🚨 CRITICAL FIX: Complete farmer/establishment data for ProductDetail.tsx
                    "id": str(establishment.public_id) if establishment else None,
                    "name": establishment.name if establishment else "Farm",
                    # Optional establishment/grower photo — first image from
                    # establishment.album if present. Consumed by
                    # GrowerStoryCard.tsx (Avatar src). Null when farm hasn't
                    # uploaded a profile photo; Avatar falls back to initials.
                    "establishment_image": _first_album_image_url(establishment),
                    "description": (
                        _public_farm_text(establishment.description, _supplier_names) if establishment else ""
                    ),
                    # 2026-06 audit P1 (location PII): street address, exact coords and
                    # zip are WITHHELD from the public QR payload — same rationale as the
                    # contact strip below (P2-6) and the printed-GPS removal in
                    # ParcelMapInfo (2026-06). The consumer UI shows only city/state, and
                    # the map uses the parcel's location_disclosure_level-gated geo; exposing
                    # establishment address/coords here bypassed that privacy control and
                    # leaked the farm's exact location to any anonymous API caller.
                    "address": None,
                    "city": establishment.city if establishment else None,
                    "state": establishment.state if establishment else None,
                    "country": establishment.country if establishment else None,
                    "zone": establishment.zone if establishment else None,
                    "latitude": None,
                    "longitude": None,
                    # 2026-06 audit P2-6: the farm's direct contact (incl. the named contact
                    # person — PII) is INTENTIONALLY withheld from the public QR payload. A
                    # random shopper must not get the producer's personal phone/email/name; a
                    # wholesale buyer reaches the farm through the BuyerDocRequest form, which
                    # the farm controls. This endpoint is anonymous (no story-vs-proof distinction
                    # server-side), so contact is stripped unconditionally rather than gated.
                    "contact_person": None,
                    "contact_phone": None,
                    "contact_email": None,
                    "email": None,
                    "phone": None,
                    # P1 (location PII): zip narrows the farm to a few sq mi; city/state
                    # already cover the public "location" string. Withheld.
                    "zip_code": None,
                    # 🔴 2026-09-08 — establishment free text is vendor-redacted too.
                    #
                    # `public_free_text` polices financial and verification CLAIMS; it has never
                    # known a supplier name. Measured on the live payload for this very farm:
                    # the event prose was redacted correctly while the profile published
                    # `soil_types: [... "Purchased OMRI compost (Rexius)" ...]` — a real supplier
                    # named on the same page the events were being cleaned for.
                    "about": _public_farm_text(establishment.about, _supplier_names) if establishment else None,
                    "main_activities": (
                        _public_farm_text(establishment.main_activities, _supplier_names) if establishment else None
                    ),
                    "location_highlights": (
                        _public_farm_text(establishment.location_highlights, _supplier_names) if establishment else None
                    ),
                    "custom_message": (
                        _public_farm_text(establishment.custom_message, _supplier_names) if establishment else None
                    ),
                    "crops_grown": establishment.crops_grown if establishment else None,
                    # `sustainability_practices` is DELIBERATELY not published (removed 2026-08-07).
                    #
                    # It was a farmer-authored free-text LIST rendered to shoppers as green
                    # leaf chips. Redaction through public_free_text_list() was not enough: the
                    # verb-based patterns caught "USDA-verified" but not the far more common
                    # noun-shaped label, so "USDA Organic Certified", "Certified Organic" and
                    # "Real Organic Project Certified" all passed through intact — and three
                    # demo seeders shipped exactly those strings. A certification attestation
                    # with no database backing, styled as a trust signal, is the FTC
                    # 16 CFR 260.6 / EU ECGT 2024/825 defect this codebase has now hit five
                    # times on five different surfaces.
                    #
                    # Certification claims have one authoritative home: the Certification
                    # table, gated by history/services/claim_authority.py, which will only
                    # say "Verified via USDA Organic Integrity Database" for an actual
                    # database match. A free-text field can never clear that bar, so it does
                    # not get a second, unguarded route to the same shopper.
                    #
                    # Same disposition as `farming_method` below: still authored by the
                    # producer, still stored, still shown on the farm profile — just not
                    # published. Mirrored for the producer UI in
                    # trazo-app/src/config/consumerVisibility.ts.
                    #
                    # `is_active` and `employee_count` were dropped at the same time: both
                    # shipped on the wire and were rendered by nothing.
                    "total_acreage": establishment.total_acreage if establishment else None,
                    "year_established": establishment.year_established if establishment else None,
                    "establishment_type": establishment.establishment_type if establishment else None,
                    # `farming_method` is DELIBERATELY not published.
                    #
                    # It is a free-text CharField the farmer types (no choices), and the
                    # database holds "sustainable" and "Regenerative Agriculture" alongside
                    # "organic". Shipping that raw to shoppers publishes a self-asserted
                    # environmental claim with no substantiation — an FTC 16 CFR 260.6
                    # general-benefit claim, and under EU ECGT 2024/825 (live 2026-09-27) a
                    # self-created sustainability label. Its neighbour
                    # `sustainability_practices` was withheld outright for the same reason
                    # (see above) after redaction proved insufficient.
                    #
                    # Organic status reaches consumers through `organic_claim`, which
                    # ConsumerClaimValidator substantiates. A farmer-typed second opinion
                    # sitting next to a validated claim can only weaken or contradict it.
                    #
                    # No consumer component rendered this field — it was dead weight on the
                    # wire. The value is still used server-side (is_organic_production) and
                    # still shown to the producer; it just is not published.
                    "location": city_state_label(establishment),
                    # STRUCTURED certifications only — never the free-text field.
                    #
                    # 🔴 2026-08-12: this used to read
                    #     `certification_data or establishment.certifications`
                    # so an operation with NO Certification rows fell back to
                    # `Establishment.certifications`, a plain TextField the farmer types into.
                    # Measured on the wire, that published:
                    #   "Carbon Trust Standard, Regenerative Organic Certified, GlobalGAP,
                    #    SQF Level 2, Rainforest Alliance"
                    # — five third-party certification names, asserted on an anonymous consumer
                    # surface, with nothing in the database behind any of them and no
                    # verification status attached. That is the self-created-label class
                    # (EU ECGT 2024/825, live 2026-09-27) and an FTC 16 CFR 260.6 claim.
                    #
                    # The `or` also swapped the TYPE: every claim-safety control downstream —
                    # `filter_certifications_for_consumer`, `consumer_display_status`, the
                    # JSON-LD `verified_via_database` filter — operates on a list of cert
                    # OBJECTS. A bare string satisfies `or` and then sails past all of them,
                    # because there is no `.status` on a string to check. The fallback was
                    # therefore not a degraded version of the safe path; it was a bypass of it.
                    #
                    # An operation with no certification rows now reports none, which is the
                    # true answer. The free-text field is still shown to the producer and still
                    # used server-side; it is simply not a consumer claim.
                    "certifications": certification_data,
                    # Farmer-authored JSON lists. Until 2026-09-08 these reached the wire with
                    # NO scrubber of any kind — not even `public_free_text`.
                    "water_sources": (
                        redact_supplier_names(establishment.water_sources, _supplier_names) if establishment else None
                    ),
                    "soil_types": (
                        redact_supplier_names(establishment.soil_types, _supplier_names) if establishment else None
                    ),
                    # `climate_zone` and `conservation_practices` dropped 2026-08-07: both were
                    # on the wire and rendered by no consumer component (FarmModal drops them
                    # explicitly). Payload bloat, and a field nobody renders is a field nobody
                    # re-reads the privacy rules for on the day they add a render.
                    "irrigation_methods": (
                        redact_supplier_names(establishment.irrigation_methods, _supplier_names)
                        if establishment
                        else None
                    ),
                    # Nested company data
                    "company": (
                        {
                            "name": (
                                establishment.company.name if establishment and establishment.company else "Company"
                            ),
                            "description": (
                                public_free_text(establishment.company.description)
                                if establishment and establishment.company
                                else ""
                            ),
                            # P1 (location PII): company street address withheld — see farmer block.
                            "address": None,
                            "city": establishment.company.city if establishment and establishment.company else None,
                            "state": establishment.company.state if establishment and establishment.company else None,
                            "country": (
                                establishment.company.country if establishment and establishment.company else None
                            ),
                            # P2-6: company direct contact withheld from the public payload
                            # (buyers use the BuyerDocRequest form). See farmer block above.
                            "email": None,
                            "phone": None,
                            "website": (
                                establishment.company.website if establishment and establishment.company else None
                            ),
                            "facebook": (
                                establishment.company.facebook if establishment and establishment.company else None
                            ),
                            "instagram": (
                                establishment.company.instagram if establishment and establishment.company else None
                            ),
                            "logo": (
                                establishment.company.logo.url
                                if establishment and establishment.company and establishment.company.logo
                                else None
                            ),
                            # fiscal_id (company tax ID) + contact_email are sensitive business
                            # data, not consumer transparency — withheld from the public payload (P2-6).
                            "fiscal_id": None,
                            "contact_email": None,
                            "total_establishments": (
                                establishment.company.establishment_set.count()
                                if establishment and establishment.company
                                else 0
                            ),
                            "total_parcels": (
                                establishment.company.establishment_set.aggregate(total=Count("parcels"))["total"] or 0
                                if establishment and establishment.company
                                else 0
                            ),
                        }
                        if establishment
                        else {"name": "Company", "total_establishments": 0, "total_parcels": 0}
                    ),
                },
                "product": {"name": history.product.name if history.product else "Farm Product"},
                "reputation": history.reputation or 0,
                # Phase 4 — consumer review aggregate for the hero rating line.
                # Distinct from `reputation` (farmer-side metric): this is real
                # consumer feedback, shown only when count > 0.
                "reviews": _build_reviews_summary(history),
                "timeline": public_history_data.get("events", []),
                # Harvest completion date for the consumer hero/harvest pillar.
                # The formatter's farm_context.production_period is popped above,
                # so without this the frontend never receives a harvest date.
                "finish_date": history.finish_date.isoformat() if history.finish_date else None,
                # 🔴 2026-09-08 — `quality_grade` and `harvest_method` are NOT published.
                #
                # The season-close form collects both under a section whose own label reads
                # "Printed in your certifier packet alongside the lot number and yield. Not
                # shown to consumers." (StandardFinishProductionForm). They were shipping here,
                # on the anonymous payload, and rendering on the buyer page's Harvest card — so
                # the form was making a privacy promise the API broke. A grade is also a
                # commercial quality assertion a shopper cannot check and a packer's paperwork
                # can contradict.
                #
                # Both remain on the model, in the certifier packet (which reads the model
                # directly), in the producer UI and in the free records-export ZIP. This is the
                # form's promise being honoured, not data being lost.
                "harvestDetails": {
                    "amount": history.production_amount,
                    "unit": history.production_unit,
                    "lot_number": history.lot_id,
                },
                "parcel": _build_public_parcel(history.parcel),
                "images": public_history_data.get("images", []),  # Photo gallery for ProductDetail
            }
        )  # Close the response_data.update() call

        # Specimen marking (2026-08-30). From 2026-08-21 `common/specimen.py` has been the one
        # place that decides whether an artifact describes a REAL operation, and every EXPORT
        # surface consults it — packet, CSV, OSP modules, workbooks, PUR. The consumer product
        # page is the sibling that never got wired. `Establishment.is_demo` was already True on
        # every seeded farm and `is_specimen()` already read it; this payload asked neither.
        #
        # So `consumer.trazo.io/production/<uuid>` served Solana Verde Organic Ranch — a 285-acre
        # Fallbrook operation invented by `_solana_verde_base.py`, naming CCOF and the Xerces
        # Society as its certifiers — in a shape byte-identical to a real grower's lot. That is
        # exactly the defect class the specimen module was written for, one surface over, and the
        # dominant defect class in this codebase generally: fixed on the audited surface, alive on
        # its sibling.
        #
        # Two deliberate choices:
        #
        # * Marked for EVERY caller, owner included, and therefore placed ABOVE the `is_owner`
        #   gate below. Whether a farm's records are invented is a fact about the farm, not a
        #   function of who is looking — unlike the transparency score, which genuinely is
        #   audience-dependent.
        # * On the PAYLOAD, not only in the UI. This JSON is public and scrapable whatever the
        #   page chooses to render, and the export path learned the same lesson when marking the
        #   packet PDF but not its CSV was considered.
        #
        # The default stays load-bearing in the same direction as the export path: `is_specimen()`
        # resolves anything it cannot read to False, because marking a REAL lot tells a buyer that
        # a legitimate operation's records are a demonstration.
        if is_specimen(establishment):
            response_data["specimen"] = {
                "is_specimen": True,
                "title": SPECIMEN_TITLE,
                "body": SPECIMEN_BODY,
            }

        # Claim-safety gate (2026-06, widened 2026-09-05): the self-assigned transparency SCORE
        # was a farmer-dashboard engagement KPI, never a consumer-facing claim — a self-created
        # "% documented / data-quality grade" served to shoppers is the self-declared
        # sustainability-label class banned by EU ECGT 2024/825 (live 2026-09-27) and an FTC
        # 16 CFR 260.4 general-benefit risk, scrapable from this JSON whatever the UI hides.
        # Until 2026-09-05 the OWNER still received the graded headline, `detailed_view` and the
        # authored baseline; no producer surface rendered them, so those keys are no longer
        # built at all (see the response assembly above). What remains here is the one rule that
        # still has work to do, now applied to EVERY caller: the per-category breakdown the
        # calculator emits mixes farm FACTS (counts) with Trazo's authored baseline and grades,
        # and only the facts may travel.
        standard_view = response_data.get("standard_view")
        if isinstance(standard_view, dict):
            details = standard_view.get("transparency_details")
            if isinstance(details, dict):
                # The rule this block enforces, stated once so future keys are
                # classified rather than remembered (2026-08-10 USDA audit, P4-F1):
                #
                #   PUBLISH facts about the FARM. Never publish Trazo's authored
                #   BASELINE, nor the scoring machinery that applies it.
                #
                # Stripping the quotient while shipping its divisor was a rename, not
                # a demotion: `actual_events: 12` + `expected_events: 13` is the 92%
                # grade, reconstructable by division, and the per-category breakdown
                # made the reconstruction exact rather than approximate.
                #
                # `actual_events` is a fact — this farm documented 12 things.
                # `expected_events` is not a fact about the farm at all: it is Trazo's
                # opinion of how many events this crop SHOULD have. That is precisely
                # the "baseline Trazo authored" the note below already refuses to ship,
                # so the baseline itself has to go with the grade computed from it.
                # EU ECGT 2024/825 (live 2026-09-27); FTC 16 CFR 260.6.
                breakdown = details.get("category_breakdown")
                if isinstance(breakdown, dict):
                    for category in breakdown.values():
                        if isinstance(category, dict):
                            category.pop("completeness_percentage", None)
                            # Added with the key itself (2026-08-04). `records_completeness_percentage`
                            # is the same self-graded coverage measure with the photo penalty
                            # removed — strictly MORE flattering, and still Trazo grading a farm
                            # against a baseline Trazo authored. It is a producer-dashboard
                            # number; shipping it here would reopen exactly the leak
                            # `test_consumer_qr_privacy_regression` pins. Counts stay, grades go.
                            category.pop("records_completeness_percentage", None)
                            category.pop("status", None)
                            # Per-category denominators and scoring machinery, same rule
                            # as `expected_events` above. `expected_count` is the authored
                            # baseline; `requires_photos` and the essential/recommended
                            # `photo_tier_summary` are Trazo-authored tiers stating what
                            # this category OUGHT to carry; `anti_gaming_applied` is an
                            # internal scoring flag. None describe the farm.
                            # Kept, because each is a fact the farm produced:
                            # `actual_count` and the photo counts renamed just below.
                            category.pop("expected_count", None)
                            category.pop("requires_photos", None)
                            category.pop("anti_gaming_applied", None)
                            category.pop("photo_tier_summary", None)
                            # P4-F5. These photographs were uploaded by the grower and
                            # checked by nobody, so "verified" is a claim the data does not
                            # support — the same word this project reserves for a USDA
                            # Organic Integrity Database match and enforces through
                            # `claim_authority`. The key name travels on the wire and is
                            # scrapable whatever the UI renders, so it is the claim.
                            #
                            # Renamed HERE rather than in `transparency_calculator`: the
                            # internal name reaches the authenticated producer surface too,
                            # and this block is the one chokepoint that shapes what an
                            # anonymous caller sees. Renaming the calculator is a wider
                            # change with its own consumers — worth doing, separately.
                            if "photo_verified_count" in category:
                                category["photo_documented_count"] = category.pop("photo_verified_count")
                            # Run 8b F1 (2026-10-14). The RATE is dropped, not renamed. Until
                            # today it travelled as `photo_documentation_rate`: photos per
                            # documented practice, as a percentage, which is a "% documented"
                            # figure about the farm's own records (transparency-first.md: counts
                            # only). It was also wrong on its face: a category with no events
                            # reported 100.0. `actual_count` and `photo_documented_count` are
                            # the two counts it was divided from, and both stay.
                            category.pop("photo_verification_rate", None)

        return Response(response_data, status=status.HTTP_200_OK)

    except (Production.DoesNotExist, Http404):
        formatter = TransparencyResponseFormatter()
        error_response = formatter.format_error_response(
            error_message="Production not found",
            error_details="This QR code is not in our system or is not publicly available",
        )
        return Response(error_response, status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        lookup_ref = production_public_id or "unknown"
        logger.error(f"Transparency detail error for production {lookup_ref}: {str(e)}")
        formatter = TransparencyResponseFormatter()
        error_response = formatter.format_error_response(
            error_message="Service temporarily unavailable", error_details="Please try again in a moment"
        )
        return Response(error_response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _build_reviews_summary(history):
    """Aggregate consumer reviews for this production — count + average only."""
    try:
        from django.db.models import Avg, Count

        agg = history.reviews.aggregate(count=Count("id"), average=Avg("rating"))
        return {
            "count": agg["count"] or 0,
            "average": round(agg["average"], 1) if agg["average"] is not None else None,
        }
    except Exception:
        return {"count": 0, "average": None}


def _build_public_parcel(parcel):
    """
    Disclosure-gated parcel block for the public payload (Phase 3 privacy).

    A public field polygon is a theft/scouting exposure; the farmer controls
    precision via Parcel.location_disclosure_level:
      exact       — full polygon + map metadata (grandfathered existing parcels)
      approximate — center rounded to 2 decimals (~1 km), no boundary
      hidden      — no geodata at all
    """
    if not parcel:
        return {"name": None, "area": None, "polygon": None, "map_metadata": None}

    from history.services.privacy import public_parcel_geo

    geo = public_parcel_geo(parcel)
    return {
        "name": parcel.name,
        "area": parcel.area,
        "polygon": geo["polygon"],
        "map_metadata": geo["map_metadata"],
        "location_disclosure_level": geo["level"],
    }


def _public_farm_text(value, supplier_names):
    """Establishment free text on its way to the anonymous payload.

    Two independent scrubbers, because they catch different things and neither subsumes the
    other: `public_free_text` removes farm financials and unsupportable market/verification
    claims, and `redact_supplier_names` removes the operation's own commercial counterparties.
    Applied in that order so a redaction marker never confuses the claim patterns.
    """
    return redact_supplier_names(public_free_text(value), supplier_names)


def _build_organic_summary(history, certification_data, establishment, organic_claim=None):
    """
    Aggregate organic data from already-prefetched ChemicalEvents and certifications.
    Returns a consumer-facing summary — no extra DB queries.

    `organic_claim` is the dict output of ConsumerClaimValidator — the regulatory
    single source of truth for the production's organic status (certified vs
    transitioning vs self_reported vs conventional). Threaded in so the consumer
    narrative (ProductDetail.tsx) can disambiguate transitional from certified
    from self-reported farms — otherwise "reports following organic practices"
    leaks onto transitional productions whose headline says "not yet organic"
    (FTC 16 CFR 260.6(d) qualified-claim risk).
    """
    # Shared vocabulary with the lot gate and the input-status chips
    # (history/services/claim_resolver.py) — one classification, three surfaces.
    from history.services.claim_resolver import (
        ORGANIC_APPROVED_VALUES,
        PROHIBITED_INPUT_VALUES,
        event_organic_classification,
    )

    # Count organic-approved chemical inputs from prefetched events
    # Only count events where organic_approved was explicitly set (not null/blank)
    # null = farmer didn't fill this field, NOT "this input is non-organic"
    # select_related("omri_product") because `_organic_input_evidence` below routes every
    # event through `may_claim_input_listing`, which reads `delisted_on` off the related row.
    # This builds its own queryset rather than reusing the view's prefetch, so without it the
    # anonymous payload fires one extra query per chemical event.
    chemical_events = list(history.history_chemicalevent_events.select_related("omri_product").all())
    classifications = [event_organic_classification(e) for e in chemical_events]
    classified = [c for c in classifications if c]
    organic_inputs = sum(1 for c in classified if c in ORGANIC_APPROVED_VALUES)
    non_organic_inputs = sum(1 for c in classified if c in PROHIBITED_INPUT_VALUES)
    classified_count = len(classified)

    # Production-level farming method
    production_method = getattr(history, "production_method", None) or ""
    farm_method = getattr(establishment, "farming_method", None) or ""
    is_organic_production = production_method == "organic" or farm_method == "organic"

    # Consumer claim status is the regulatory single source of truth — the badge
    # (OrganicClaimBadge, gated on organic_claim.status) and the narrative
    # (gated on certification_verified/is_in_transition below) must agree.
    # When organic_claim is available, derive both flags from it so
    # ConsumerClaimValidator is the sole authority for certified/transitioning
    # state. Fallback display_name scan runs only when organic_claim is missing
    # (exception path at the caller, or direct test invocations).
    claim_status = (organic_claim or {}).get("status")

    # 🔴 2026-09-16 — no organic narrative at all for a fabricated operation.
    #
    # `ConsumerClaimValidator` now returns status="specimen", so the two comparisons below stop
    # matching on their own and `certification_verified` goes False. That alone is not enough:
    # `is_organic_production` (the farm's own `production_method` dropdown) would still make
    # `is_organic_farm` True, and the page would fall through to the self-reported narrative,
    # "This farm reports following organic practices" — a statement about a farm that does not
    # exist. The input chips below ("every input is recorded as approved for organic use") are
    # the same class.
    #
    # Read from the ESTABLISHMENT rather than only from `organic_claim`, because this function
    # is also called on the caller's exception path with `organic_claim=None`: a negative
    # assertion has to prove it read something.
    from common.specimen import is_specimen

    if is_specimen(establishment) or claim_status == "specimen":
        return None

    is_in_transition = claim_status == "transitioning"
    if organic_claim is not None:
        has_verified_organic = claim_status == "certified_organic"
        has_self_reported_organic = claim_status == "self_reported"
    else:
        has_verified_organic = any(
            c.get("display_name", "").lower().startswith("usda organic") and c.get("status") == "verified_via_database"
            for c in (certification_data or [])
        )
        has_self_reported_organic = any(
            c.get("display_name", "").lower().startswith("usda organic") and c.get("status") == "self_reported"
            for c in (certification_data or [])
        )

    # Only return summary when the farm is actually an organic operation.
    # Having organic-approved inputs alone does NOT make it an organic farm —
    # a conventional farm can use OMRI-listed products without being organic.
    # Transitional productions also qualify — the narrative must explain the
    # transition state instead of claiming "following organic practices."
    is_organic_farm = is_organic_production or has_verified_organic or has_self_reported_organic or is_in_transition
    if not is_organic_farm:
        return None

    return {
        "is_organic_farm": is_organic_farm,
        "claim_status": claim_status,
        "is_in_transition": is_in_transition,
        "certification_verified": has_verified_organic,
        "certification_self_reported": has_self_reported_organic and not has_verified_organic,
        # Only include input stats when farmers actually classified their inputs
        "has_input_data": classified_count > 0,
        "total_chemical_inputs": classified_count,
        "organic_approved_inputs": organic_inputs,
        "all_inputs_organic": classified_count > 0 and organic_inputs == classified_count,
        # P4-F6. The counts above are built from `organic_approved`, a GROWER DROPDOWN whose
        # values include "omri_listed" — the grower picking that label, not a catalog match.
        # `claim_authority.may_claim_input_listing()` already tiers exactly this per input,
        # after an anonymous payload said "OMRI Listed" for an input with no OMRI row and no
        # National List citation (2026-08-09). That fix landed on the per-input chip and never
        # on this aggregate, so the summary asserted, in one number, more than the authority
        # permits each input to claim individually — the seventh instance of "fixed on the
        # audited surface, alive on its sibling".
        #
        # The counts must never travel WITHOUT their basis, so the basis ships in the same
        # object and names the WEAKEST evidence behind the numbers. A caller rendering the
        # figures alone now has no excuse.
        #
        # Run 8b F1 (2026-10-14): `organic_input_percentage` is gone. The consumer page renders
        # "N of M inputs" from the two counts above and never read the percentage; on an
        # anonymous payload a percentage of the grower's own records is the self-graded class
        # transparency-first.md withholds (counts only).
        **_organic_input_evidence(chemical_events),
    }


#: Weakest-first, so the first tier present is the honest headline. `contradicted` leads because
#: it is not weak evidence FOR the claim — it is evidence AGAINST it, and an aggregate containing
#: one must never present as though it were merely under-documented.
#: `conditional` sits second: a § 205.602 entry the CFR permits only for one named use is not
#: evidence FOR an organic claim the way an unconditional § 205.601 citation is, and an
#: aggregate containing one must say so rather than presenting as plain grower_reported.
_INPUT_EVIDENCE_ORDER = ("contradicted", "conditional", "grower_reported", "national_list", "catalog_matched")


def _organic_input_evidence(chemical_events):
    """Tier the evidence behind the organic-input counts, using the one claim authority.

    Returns the per-tier counts plus `organic_input_basis`, the weakest tier represented — an
    aggregate is only as strong as its weakest member, and "one of these twelve was matched to
    the OMRI catalog" does not license speaking for the other eleven.
    """
    from history.services.claim_authority import (
        LABEL_INPUT_NATIONAL_LIST,
        LABEL_INPUT_NATIONAL_LIST_CONDITIONAL,
        LABEL_INPUT_NATIONAL_LIST_PROHIBITED,
        LABEL_INPUT_NATIONAL_LIST_WITH_CONDITION,
        LABEL_INPUT_OMRI_LISTED,
        LABEL_INPUT_WSDA_LISTED,
        may_claim_input_listing,
    )

    # Imported here, not at module scope, because the caller does the same — these live in
    # claim_resolver and the module-level import would be a cycle.
    from history.services.claim_resolver import ORGANIC_APPROVED_VALUES, event_organic_classification

    counts = {"catalog_matched": 0, "national_list": 0, "grower_reported": 0, "conditional": 0, "contradicted": 0}
    for event in chemical_events:
        if event_organic_classification(event) not in ORGANIC_APPROVED_VALUES:
            continue
        label = may_claim_input_listing(event).safe_label
        if label in (LABEL_INPUT_OMRI_LISTED, LABEL_INPUT_WSDA_LISTED):
            # Both are catalog matches. WSDA added 2026-09-02: a new label with no branch here
            # fell into the `else` and was counted as GROWER_REPORTED — the inverse of that
            # branch's own rule, reporting the grower's word for an input Trazo holds a
            # third-party listing for. A new evidence label must be routed here in the same
            # change that creates it.
            counts["catalog_matched"] += 1
        elif label == LABEL_INPUT_NATIONAL_LIST:
            counts["national_list"] += 1
        elif label in (LABEL_INPUT_NATIONAL_LIST_CONDITIONAL, LABEL_INPUT_NATIONAL_LIST_WITH_CONDITION):
            # A National List entry with a condition of use: § 205.602 for one stated use, or
            # § 205.601 under its entry's words (documented deficiency, structural use only).
            # Not `contradicted` (the CFR writes the use out as permitted), and not
            # `national_list` either, because that tier means an unconditional § 205.601
            # allowance. Its own bucket, so the basis a caller reads says "there is a condition
            # attached" instead of quietly rounding to either side.
            counts["conditional"] += 1
        elif label == LABEL_INPUT_NATIONAL_LIST_PROHIBITED:
            # The grower classified this input as organic-approved and § 205.602 lists the
            # substance as PROHIBITED. `resolve_lot_organic_eligibility` already refuses the
            # lot-level organic claim on exactly this signal, but `all_inputs_organic` reads
            # only the grower's dropdown — so without this bucket the summary would report
            # "100%, grower_reported" beside a lot the claim gate had already failed, and the
            # two halves of one payload would contradict each other.
            #
            # Zero such rows exist today (checked 2026-08-11). Counted anyway: this costs one
            # branch now, and the recurring lesson of this codebase is that the surface nobody
            # checked is the one that leaks.
            counts["contradicted"] += 1
        else:
            # The grower's own dropdown, or unclassified. Never promote: absence of catalog
            # evidence is not evidence of a catalog match.
            counts["grower_reported"] += 1

    present = [tier for tier in _INPUT_EVIDENCE_ORDER if counts[tier]]
    return {
        "organic_input_evidence": counts,
        "organic_input_basis": present[0] if present else None,
    }


# Fields that only get filled in when the amendment was BOUGHT. Every one of them names a
# counterparty or a piece of that counterparty's paperwork — a supplier, the label's maker, an
# invoice, a delivery ticket's lot number — so none of them can be filled in about a pile the
# operation built itself.
#
# Deliberately does NOT include the compost PROCESS fields (method, feedstock, peak temp,
# turnings, C:N). Those record § 205.203(c)(2) conformance and a grower applying purchased
# compost has to hold them too — they say the compost was made properly, never who made it.
_OFF_FARM_COMPOST_SIGNALS = (
    "amendment_supplier_name",
    "amendment_manufacturer",
    "amendment_purchase_invoice",
    "amendment_purchase_date",
    "amendment_quantity_purchased",
    # A manufacturer's lot/batch number off a bag or delivery ticket. An operation's own pile is
    # identified by `compost_unit_id` (the windrow ID on its NOP 5021 log), not by this.
    "amendment_lot_number",
    "receipt_document",
)


def _compost_was_bought_in(event):
    """True when this compost event carries any evidence of being sourced off the farm.

    Fails CLOSED, which is the whole point: the cost of getting this wrong in one direction is a
    practice-based grower missing one chip on their page, and in the other it is Trazo telling
    shoppers a farm composts on site when its own record names the supplier it bought from.
    """
    for field in _OFF_FARM_COMPOST_SIGNALS:
        value = getattr(event, f"{field}_id", None) if field == "receipt_document" else getattr(event, field, None)
        if value not in (None, ""):
            return True
    return False


def _build_practice_summary(history):
    """Aggregate documented soil/regenerative PRACTICE facts for consumer display.

    GTM-v3 "real vs. fake organic" differentiator: a practice-based regenerative grower
    (integrated grazing, cover crops, on-farm compost) should be visibly distinguishable from
    an input-substitution "organic" neighbor — but ONLY through the FACTS the farmer actually
    logged, never a grade, verdict, or regenerative badge (transparency-first.md; EU ECGT
    2024/825; FTC 16 CFR 260.6). The difference shows itself: a real grower's list is full
    because they did and logged the practices; a spray-style farm's is empty.

    Reads already-prefetched SoilManagementEvents — zero extra DB queries. Returns None when
    no qualifying practices exist (the card section is simply hidden).
    """
    soil_events = list(history.history_soilmanagementevent_events.all())
    if not soil_events:
        return None

    grazing = [e for e in soil_events if e.type == SoilManagementEvent.GRAZING]
    cover_crop = [e for e in soil_events if e.type == SoilManagementEvent.COVER_CROP]
    compost = [e for e in soil_events if e.type == SoilManagementEvent.COMPOSTING]

    practices = []

    if grazing:
        animals = sorted({(e.animal_type or "").strip().lower() for e in grazing if e.animal_type})
        total_days = sum(e.grazing_duration_days or 0 for e in grazing)
        practices.append(
            {
                "key": "integrated_grazing",
                "count": len(grazing),
                "animal_types": animals,
                "total_grazing_days": total_days or None,
            }
        )

    if cover_crop:
        species = sorted(
            {
                (e.extra_data or {}).get("cover_crop_species", "").strip()
                for e in cover_crop
                if isinstance(e.extra_data, dict) and (e.extra_data or {}).get("cover_crop_species")
            }
        )
        practices.append({"key": "cover_crops", "count": len(cover_crop), "species": species})

    # 🔴 2026-08-31 — "on-farm compost" is a claim about WHO MADE IT, and this used to make it
    # for every COMPOSTING event on the season. Measured on a real lot: an event naming
    # `amendment_supplier_name` "Agromin, Oxnard", an invoice number, and a feedstock of
    # "green waste, yard trimmings and horse bedding" — compost bought by the pallet — published
    # the chip "On-farm compost" to shoppers. The record did not merely fail to support the
    # claim, it contradicted it, which is the FTC 16 CFR 260.6 case in its plainest form.
    #
    # Both facts are worth publishing, so the split is by claim rather than by suppression: a
    # pile the operation built is `on_farm_compost`, compost it bought and spread is
    # `compost_applied`. A season doing both gets both, with honest counts.
    if compost:
        on_farm = [e for e in compost if not _compost_was_bought_in(e)]
        bought_in = [e for e in compost if _compost_was_bought_in(e)]
        if on_farm:
            methods = sorted({(e.compost_method or "").strip() for e in on_farm if e.compost_method})
            practices.append({"key": "on_farm_compost", "count": len(on_farm), "methods": methods})
        if bought_in:
            # No `methods`: the windrow/static-pile method of compost the operation BOUGHT is the
            # supplier's process, and attributing it here is how "on-farm" crept in to begin with.
            practices.append({"key": "compost_applied", "count": len(bought_in)})

    # Biodiversity / habitat (HD = developed habitat, NS = nesting/shelter structures). FACTS only —
    # the habitat types and structure totals the farmer logged, never a biodiversity score/index or a
    # species-richness number (banned self-label class). The living-floor / bugs / birds proof rides
    # on the event photos, surfaced elsewhere.
    habitat_dev = [e for e in soil_events if e.type == SoilManagementEvent.HABITAT_DEVELOPMENT]
    nesting = [e for e in soil_events if e.type == SoilManagementEvent.NESTING_SHELTER]

    # earliest install/establish date drives the consumer maturity story ("hedgerow since 2019")
    def _earliest_install(events):
        dates = [e.habitat_install_date for e in events if getattr(e, "habitat_install_date", None)]
        return min(dates).isoformat() if dates else None

    if habitat_dev:
        habitat_types = sorted({(e.habitat_type or "").strip() for e in habitat_dev if e.habitat_type})
        practices.append(
            {
                "key": "habitat_development",
                "count": len(habitat_dev),
                "habitat_types": habitat_types,
                "established_since": _earliest_install(habitat_dev),
            }
        )

    if nesting:
        structures = sorted({(e.habitat_type or "").strip() for e in nesting if e.habitat_type})
        total_structures = sum(e.habitat_structure_count or 0 for e in nesting)
        practices.append(
            {
                "key": "nesting_shelter",
                "count": len(nesting),
                "structures": structures,
                "total_structures": total_structures or None,
                "installed_since": _earliest_install(nesting),
            }
        )

    if not practices:
        return None

    return {"practices": practices}


def _first_album_image_url(establishment):
    """Return a stable URL for the first image in the establishment's album.

    Consumed by the consumer QR farmer block as the grower-story avatar source.
    Returns None when the establishment has no album, no images, or the image
    row has no resolvable URL — callers (GrowerStoryCard.tsx) render an
    initials-based fallback in that case.
    """
    if not establishment or not getattr(establishment, "album_id", None):
        return None
    first_image = establishment.album.images.first()
    if first_image is None:
        return None
    return getattr(first_image, "url", None)


def _get_blockchain_verification_data(history):
    """Extract blockchain verification data from History extra_data for consumer display."""
    extra = history.extra_data if isinstance(history.extra_data, dict) else {}

    tx_hash = extra.get("blockchain_tx_hash") or extra.get("blockchain_transaction")
    is_verified = bool(tx_hash) and extra.get("blockchain_verified", False)

    # Determine explorer URL based on settings
    from django.conf import settings

    explorer_url = getattr(settings, "POLYGON_EXPLORER_URL", "https://polygonscan.com")

    finalization_hash = extra.get("finalization_hash")

    return {
        "tx_hash": tx_hash,
        "verified": is_verified,
        "is_finalized": bool(finalization_hash),
        "block_number": extra.get("blockchain_block_number"),
        "submitted_at": extra.get("blockchain_submitted_at"),
        "finalization_hash": finalization_hash,
        "finalization_event_count": extra.get("finalization_event_count"),
        "network": getattr(settings, "BLOCKCHAIN_NETWORK_NAME", "polygon"),
        "explorer_url": f"{explorer_url}/tx/{tx_hash}" if tx_hash else None,
    }


def _compute_finalization_hash(history):
    """Re-compute the finalization hash from the current state of events.

    Delegates to History.compute_finalization_hash() — single source of truth.
    """
    return history.compute_finalization_hash()


def _recompute_production_data_hash(history, finalization_hash):
    """Re-compute the blockchain data hash from current DB state.

    Delegates to carbon.tasks.build_blockchain_raw_data() — single source of truth.
    The finalization_hash parameter is unused since build_blockchain_raw_data reads
    it directly from history.extra_data, but kept for API compatibility.
    """
    try:
        from carbon.tasks import build_blockchain_raw_data

        company_id = None
        if history.parcel and history.parcel.establishment:
            company_id = history.parcel.establishment.company_id

        _raw_data, data_hash, *_ = build_blockchain_raw_data(history, company_id)
        return data_hash

    except Exception as e:
        logger.error("Failed to recompute production data hash for %s: %s", history.id, e)
        return None


@api_view(["GET"])
@permission_classes([AllowAny])
def verify_blockchain(request, production_public_id=None):
    """
    Public endpoint for consumer blockchain verification.

    Three-layer integrity verification:
      Layer 1 (fast, no network): Re-hash current events, compare to stored
              finalization hash in our DB.  Catches accidental event edits.
      Layer 2 (on-chain read):    Re-build the full raw_data submitted to
              blockchain, hash it, and compare against the immutable dataHash
              stored in the smart contract.  This is the REAL verification —
              even if someone tampers with both events AND our DB hash, the
              on-chain hash will catch it.
      Layer 3 (consumer-verifiable): Return the tx_hash + explorer link so
              anyone can independently inspect the on-chain record.
    """
    try:
        if production_public_id is None:
            return Response(
                {"error": "Production identifier required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        lookup_kwargs = {"published": True, "public_id": production_public_id}

        history = get_object_or_404(Production, **lookup_kwargs)
        verification_data = _get_blockchain_verification_data(history)
        extra = history.extra_data if isinstance(history.extra_data, dict) else {}

        # ------------------------------------------------------------------
        # Layer 1: Event integrity (DB-only, fast)
        # ------------------------------------------------------------------
        stored_finalization_hash = extra.get("finalization_hash")
        current_finalization_hash = None
        current_event_count = 0
        layer1_status = "unknown"
        layer1_detail = None

        if stored_finalization_hash:
            # history.seals checks the stored seal at the version it was written with. A version-1
            # seal with index ties that no event order reproduces is `inconclusive`, never
            # `tampered`: v1's order is not fixed, so it cannot tell a changed record from a changed
            # row order (a season resealed on 2026-11-05 failed this check minutes later with
            # nothing changed). `inconclusive` is neither "intact" nor "tampered" on the QR page.
            from history.seals import INCONCLUSIVE, INTACT, MISMATCH, NO_SEAL
            from history.seals import verify as verify_seal

            check = verify_seal(history)
            current_event_count = check.event_count or 0
            if check.status == INTACT:
                layer1_status = "intact"
                layer1_detail = f"All {current_event_count} events match the sealed record."
            elif check.status == MISMATCH:
                layer1_status = "tampered"
                layer1_detail = (
                    "Event data does not match the finalization record. "
                    "Data may have been modified after it was sealed."
                )
                logger.warning("Layer-1 mismatch for production %s (seal version %s)", history.id, check.version)
            elif check.status == INCONCLUSIVE:
                layer1_status = "inconclusive"
                layer1_detail = check.detail
            elif check.status == NO_SEAL:
                layer1_status = "no_hash"
                layer1_detail = "This production was not finalized with a hash record."
            else:
                logger.error("Layer-1 check failed for production %s: %s", history.id, check.detail)
                layer1_status = "check_failed"
                layer1_detail = "Unable to perform event integrity check."
        else:
            layer1_status = "no_hash"
            layer1_detail = "This production was not finalized with a hash record."

        # ------------------------------------------------------------------
        # Layer 2: On-chain verification (reads immutable smart contract)
        # ------------------------------------------------------------------
        layer2_status = "skipped"
        layer2_detail = None
        on_chain_hash = None

        if verification_data.get("tx_hash") and extra.get("blockchain_verified"):
            try:
                from carbon.services.blockchain import BlockchainCarbonService

                blockchain_service = BlockchainCarbonService()
                on_chain_record = blockchain_service.read_on_chain_record(history.id)

                if on_chain_record:
                    on_chain_hash = on_chain_record["data_hash"]

                    # Strategy: read the immutable on-chain hash and verify it
                    # against our data using two approaches:
                    #
                    # 1) Compare stored data_hash (written at submission time)
                    #    against on-chain hash.  If they differ, our DB was
                    #    tampered — the attacker changed the stored hash to
                    #    cover their tracks, but the blockchain still has
                    #    the original.
                    #
                    # 2) Recompute data_hash from current DB state and compare
                    #    against on-chain.  If they differ, the underlying
                    #    production data was modified after submission.
                    #
                    # Both must pass for "verified".

                    stored_data_hash = extra.get("blockchain_data_hash")

                    # Check 1: stored hash vs on-chain (catches DB hash tampering)
                    stored_matches_chain = stored_data_hash is not None and stored_data_hash == on_chain_hash

                    # Check 2: recomputed hash vs on-chain (catches data modification)
                    recomputed_data_hash = _recompute_production_data_hash(
                        history, current_finalization_hash or stored_finalization_hash
                    )
                    recomputed_matches_chain = (
                        recomputed_data_hash is not None and recomputed_data_hash == on_chain_hash
                    )

                    if recomputed_matches_chain:
                        # Current data matches on-chain — strongest guarantee
                        layer2_status = "verified"
                        layer2_detail = (
                            "Production data verified against immutable blockchain record. "
                            "No data has been modified since submission."
                        )
                    elif stored_matches_chain and layer1_status == "intact":
                        # Stored hash matches on-chain AND events match finalization.
                        # Recompute mismatch may be due to CarbonEntry recalculation
                        # (which doesn't affect event integrity).
                        layer2_status = "verified"
                        layer2_detail = (
                            "Blockchain record matches stored submission hash. " "Event integrity confirmed."
                        )
                    elif stored_matches_chain and layer1_status == "inconclusive":
                        # The on-chain record matches what we submitted, but layer 1 could not
                        # re-check the events (a version-1 seal with ties too wide to enumerate).
                        # Neither verified nor tampered (review of back #298).
                        layer2_status = "inconclusive"
                        layer2_detail = (
                            "Blockchain record matches the stored submission hash. The events "
                            "could not be re-checked exactly."
                        )
                    elif stored_data_hash is None:
                        # Production submitted before we stored data_hash —
                        # can't do full on-chain comparison yet.
                        layer2_status = "legacy"
                        layer2_detail = (
                            "This production was submitted before on-chain verification "
                            "was enabled. Event integrity relies on Layer 1 check."
                        )
                    else:
                        layer2_status = "tampered"
                        layer2_detail = (
                            "Production data does NOT match the immutable blockchain record. "
                            "Data was modified after blockchain submission."
                        )
                        logger.warning(
                            "Layer-2 tamper detected for production %s: " "on_chain=%s, stored=%s, recomputed=%s",
                            history.id,
                            on_chain_hash,
                            stored_data_hash,
                            recomputed_data_hash,
                        )
                else:
                    layer2_status = "no_record"
                    layer2_detail = "No on-chain record found for this production."

            except Exception as e:
                logger.error("Layer-2 on-chain check failed for production %s: %s", history.id, e)
                layer2_status = "unavailable"
                layer2_detail = "Blockchain network temporarily unavailable for verification."

        # ------------------------------------------------------------------
        # Determine overall status
        # ------------------------------------------------------------------
        # Layer 2 (on-chain) is the authoritative source when available.
        # Fall back to Layer 1 (DB-only) otherwise.
        if layer2_status == "tampered" or layer1_status == "tampered":
            integrity_status = "tampered"
            # Prefer layer 2 detail (on-chain is authoritative)
            integrity_detail = layer2_detail if layer2_status == "tampered" else layer1_detail
        elif layer1_status == "inconclusive":
            # Layer 2 re-hashes the stored seal and carbon totals, not the events, so even a
            # "verified" layer 2 cannot make events intact that layer 1 could not check.
            integrity_status = "inconclusive"
            integrity_detail = layer1_detail
        elif layer2_status == "verified":
            integrity_status = "intact"
            integrity_detail = layer2_detail
        elif layer2_status == "legacy" and layer1_status == "intact":
            # Pre-upgrade production: rely on Layer 1 only
            integrity_status = "intact"
            integrity_detail = layer1_detail
        elif layer1_status == "intact":
            integrity_status = "intact"
            integrity_detail = layer1_detail
        else:
            integrity_status = layer1_status
            integrity_detail = layer1_detail

        # ------------------------------------------------------------------
        # Build response
        # ------------------------------------------------------------------
        if not verification_data.get("tx_hash"):
            return Response(
                {
                    "status": "not_recorded",
                    # Was: status "pending" with the message "This production has not yet been
                    # submitted to blockchain. Blockchain verification occurs in monthly batch
                    # cycles." Found 2026-08-09 by the live anonymous-payload sweep, and wrong
                    # on two counts at once:
                    #
                    #   1. "Blockchain verification" is the phrasing compliance.md marks
                    #      UNSAFE — the chain shows a record was not altered after submission,
                    #      it does not verify that any farming practice happened.
                    #   2. It promised a WITHDRAWN product. `BLOCKCHAIN_ENABLED` defaults False
                    #      and the add-on was withdrawn on 2026-08-06, so "occurs in monthly
                    #      batch cycles" told a shopper to expect something that will never
                    #      arrive. "pending" said the same thing in the status field.
                    #
                    # Same class as the collateral finding the same day: withdrawing a product
                    # from the DATA is not withdrawing it from the UI, and neither is
                    # withdrawing it from the API.
                    "message": (
                        "This production has no blockchain record. The documentation below "
                        "comes from the farm's own activity log."
                    ),
                    "data_integrity": integrity_status,
                    "data_integrity_detail": integrity_detail,
                },
                status=status.HTTP_200_OK,
            )

        blockchain_status = "verified" if verification_data["verified"] else "submitted"

        if integrity_status == "tampered":
            blockchain_status = "tampered"

        return Response(
            {
                "status": blockchain_status,
                "data_integrity": integrity_status,
                "data_integrity_detail": integrity_detail,
                "on_chain_verified": layer2_status == "verified",
                "on_chain_hash": on_chain_hash,
                **verification_data,
            },
            status=status.HTTP_200_OK,
        )

    except (Production.DoesNotExist, Http404):
        return Response(
            {"error": "Production not found"},
            status=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        logger.error(f"Blockchain verification error: {str(e)}")
        return Response(
            {"error": "Service temporarily unavailable"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
