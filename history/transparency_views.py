"""
Trazo Consumer Transparency API Views
Provides transparency-first data for QR scanning experience
Eliminates competitive carbon ranking to solve farmer incentive problems

Following Trazo's main goal: Authentic transparency leadership
"""

import logging

from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from carbon.services.calculator_service import CarbonCalculatorService

from .models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from .serializers import PublicHistorySerializer
from .services.transparency_calculator import TransparencyCalculator
from .services.transparency_response_formatter import TransparencyResponseFormatter

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
def production_transparency_detail(request, production_public_id=None):
    """
    Consumer-facing transparency endpoint for QR scanning

    Returns transparency percentage and carbon data WITHOUT competitive rankings
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

        base_qs = History.objects.select_related(
            "product", "parcel__establishment__company", "parcel__establishment"
        ).prefetch_related(
            # Prefetch all 8 event types with albums and images to avoid N+1 queries
            Prefetch(
                "history_weatherevent_events",
                queryset=WeatherEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_chemicalevent_events",
                queryset=ChemicalEvent.objects.select_related("album").prefetch_related("album__images"),
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
        is_owner = False
        if request.user.is_authenticated:
            try:
                h = History.objects.select_related("parcel__establishment__company").get(**lookup_kwargs)
                if h.parcel and h.parcel.establishment and h.parcel.establishment.company:
                    is_owner = request.user.companies.filter(id=h.parcel.establishment.company_id).exists()
            except History.DoesNotExist:
                pass

        if is_owner:
            history = get_object_or_404(base_qs, **lookup_kwargs)
        else:
            history = get_object_or_404(base_qs, published=True, **lookup_kwargs)

        # Initialize services
        transparency_calculator = TransparencyCalculator()
        carbon_service = CarbonCalculatorService()

        # Calculate transparency score (NEW - solves farming incentive problem)
        transparency_data = transparency_calculator.calculate_transparency_score(history)

        # Get carbon data (EXISTING - but without competitive ranking)
        try:
            carbon_data = carbon_service.calculate_production_carbon(history.id)
            carbon_score = carbon_data.get("total_co2_kg_per_kg", 0)
            carbon_breakdown = carbon_data.get("breakdown", {})
        except Exception as e:
            logger.warning(f"Carbon calculation failed for history {history.id}: {str(e)}")
            # Don't let carbon calculation errors block transparency data
            carbon_data = {}
            carbon_score = 0
            carbon_breakdown = {}

        # Get benchmark comparison (ABSOLUTE standards, not competitive rankings)
        # Pass pre-calculated transparency_data to avoid redundant recalculation
        transparency_benchmarks = transparency_calculator.compare_with_benchmarks(
            history, transparency_data=transparency_data
        )

        # Build farm information
        establishment = history.parcel.establishment if history.parcel else None
        farm_info = {
            "name": establishment.name if establishment else "Farm",
            "location": (
                f"{establishment.city}, {establishment.state}" if establishment and establishment.city else None
            ),
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
                        verification_status__in=["verified", "self_reported"],
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
        carbon_data_formatted = {
            "total_co2_kg_per_kg": carbon_score,
            "total_emissions": carbon_data.get("total_emissions", 0),
            "total_offsets": carbon_data.get("total_offsets", 0),
            "net_footprint": carbon_data.get("net_emissions", 0),
            "usda_factors_used": True,
            "calculation_method": "USDA_EPA_factors",
        }

        transparency_data_formatted = {
            "carbonGrade": transparency_benchmarks.get("benchmark_level", "C"),
            "completeness_score": transparency_data.get("completeness_score", 0),
            "transparency_percentage": transparency_data.get(
                "transparency_percentage", 0
            ),  # FIX: Pass calculated score
        }

        # Generate transparency-based achievements
        achievements = []
        if transparency_data["transparency_percentage"] >= 90:
            achievements.append(
                {
                    "type": "complete_transparency",
                    "label": "Complete Transparency",
                    "description": "Full documentation and verification",
                }
            )

        # Check actual blockchain verification status from production extra_data
        production_extra_data = history.extra_data or {}
        is_blockchain_verified = production_extra_data.get("blockchain_verified", False)
        blockchain_tx = production_extra_data.get("blockchain_transaction", "")
        blockchain_verification_data = {
            "verified": bool(is_blockchain_verified),
            "transaction_hash": blockchain_tx if is_blockchain_verified else "",
        }

        # Get standardized response
        response_data = formatter.format_qr_response(
            production=history,
            carbon_data=carbon_data_formatted,
            transparency_data=transparency_data_formatted,
            blockchain_verification=blockchain_verification_data,
            achievements=achievements,
        )

        # Remove formatter fields that duplicate the view additions below
        for key in [
            "farm_context",
            "environmental_impact_description",
            "data_sources",
            "achievements",
            "response_format",
            "timestamp",
        ]:
            response_data.pop(key, None)

        # Add timeline events with album data (same as producer page gets)
        # This ensures photos are available on consumer page
        public_history_serializer = PublicHistorySerializer(history, context={"request": request})
        public_history_data = public_history_serializer.data

        # Use CarbonEntry as single source of truth for EPA/USDA factors usage
        # "epa_factors_based" means government-published emission factors were used in
        # the carbon calculation, NOT that USDA independently verified this farm.
        from carbon.models import CarbonEntry

        # Check if ALL carbon entries for this production used EPA/USDA factors
        # usda_factors_based=True means the USDAComplianceRecord.is_epa_factors_based
        # property confirmed: validation_method in ["enhanced_api", "local_validation"]
        # and crop_type was identified (validation ran properly)
        all_carbon_entries = list(history.carbonentry_set.all())
        total_carbon_entries = len(all_carbon_entries)
        epa_factors_based_entries = sum(1 for e in all_carbon_entries if e.usda_factors_based)

        # True when ALL carbon entries used EPA/USDA emission factors
        is_epa_factors_based = total_carbon_entries > 0 and epa_factors_based_entries == total_carbon_entries

        # NOTE: the "proof_points" object (a forward-compatible fact-count successor to the
        # transparency %) was built here and returned but consumed by ZERO frontend code — the
        # consumer page already surfaces every one of those facts directly (trust pillars =
        # practices/photos/certs, the "How It Was Grown" counts, the certification card, and the
        # blockchain status). It was dead, redundant payload weight and has been removed (2026-06
        # audit P2-3). Re-introduce it only alongside a UI that actually renders it.

        # Add progressive loading structure for backward compatibility
        response_data.update(
            {
                # IMMEDIATE LOAD - Most critical info (using new format)
                "quick_view": {
                    "transparency_score": {
                        "percentage": transparency_data["transparency_percentage"],
                        "message": transparency_data["message"],
                        "status": transparency_benchmarks["benchmark_level"],
                    },
                },
                # STANDARD LOAD (10 seconds) - Core transparency details
                "standard_view": {
                    "transparency_details": {
                        "completeness_score": transparency_data.get("completeness_score", 0),
                        "actual_events": transparency_data["actual_event_count"],
                        "expected_events": transparency_data["expected_event_count"],
                        "farming_approach": transparency_data["farming_approach"],
                        "category_breakdown": transparency_data.get("category_breakdown", {}),
                    },
                    "certifications": certification_data,
                    "organic_claim": organic_claim,  # FTC 16 CFR 260.6(d) gate
                    "organic_summary": organic_summary,
                    "practice_summary": practice_summary,  # documented facts (grazing/cover/compost)
                },
                # DETAILED LOAD (30+ seconds) - Deep insights
                "detailed_view": {
                    "transparency_insights": transparency_calculator.get_transparency_insights(
                        history, transparency_data=transparency_data
                    ),
                    "benchmark_comparison": transparency_benchmarks,
                    "improvement_suggestions": transparency_benchmarks.get("next_target", {}),
                    "verification_status": _get_verification_status(history, transparency_data=transparency_data),
                    "data_quality_indicators": {
                        "last_updated": transparency_data.get("calculation_timestamp"),
                        "data_freshness": _calculate_data_freshness(history),
                        "completeness_trend": "improving",  # Could be calculated from historical data
                    },
                },
                # Blockchain verification data for consumer-facing badge
                "blockchain_verification": _get_blockchain_verification_data(history),
                # Scoring methodology — included here so consumers know how the score
                # was calculated without needing a separate API call.
                "methodology": {
                    "description": "Transparency score based on documented agricultural events",
                    "data_source": "Farmer-reported data, not independently audited",
                    "scoring_method": "Weighted category completeness across 7 event categories",
                    "carbon_scope": "Direct operational emissions only (EPA/USDA-sourced factors)",
                    "version": "2.0",
                    "last_updated": "2026-03-21",
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
                    "description": establishment.description if establishment else "",
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
                    "about": establishment.about if establishment else None,
                    "main_activities": establishment.main_activities if establishment else None,
                    "location_highlights": establishment.location_highlights if establishment else None,
                    "custom_message": establishment.custom_message if establishment else None,
                    "is_active": establishment.is_active if establishment else True,
                    "crops_grown": establishment.crops_grown if establishment else None,
                    "sustainability_practices": establishment.sustainability_practices if establishment else None,
                    "employee_count": establishment.employee_count if establishment else None,
                    "total_acreage": establishment.total_acreage if establishment else None,
                    "year_established": establishment.year_established if establishment else None,
                    "establishment_type": establishment.establishment_type if establishment else None,
                    "farming_method": establishment.farming_method if establishment else None,
                    "location": (
                        f"{establishment.city}, {establishment.state}" if establishment and establishment.city else None
                    ),
                    "certifications": certification_data or (establishment.certifications if establishment else None),
                    "climate_zone": establishment.climate_zone if establishment else None,
                    "water_sources": establishment.water_sources if establishment else None,
                    "soil_types": establishment.soil_types if establishment else None,
                    "conservation_practices": establishment.conservation_practices if establishment else None,
                    "irrigation_methods": establishment.irrigation_methods if establishment else None,
                    # Nested company data
                    "company": (
                        {
                            "name": (
                                establishment.company.name if establishment and establishment.company else "Company"
                            ),
                            "description": (
                                establishment.company.description if establishment and establishment.company else ""
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
                "isEpaFactorsBased": is_epa_factors_based,
                "timeline": public_history_data.get("events", []),
                # Harvest completion date for the consumer hero/harvest pillar.
                # The formatter's farm_context.production_period is popped above,
                # so without this the frontend never receives a harvest date.
                "finish_date": history.finish_date.isoformat() if history.finish_date else None,
                "harvestDetails": {
                    "amount": history.production_amount,
                    "unit": history.production_unit,
                    "lot_number": history.lot_id,
                    "quality_grade": history.quality_grade,
                    "harvest_method": history.harvest_method,
                },
                "parcel": _build_public_parcel(history.parcel),
                "images": public_history_data.get("images", []),  # Photo gallery for ProductDetail
            }
        )  # Close the response_data.update() call

        # Claim-safety gate (2026-06): the self-assigned transparency SCORE is a
        # farmer-dashboard engagement KPI, NOT a consumer-facing claim. A self-created
        # "% documented / data-quality grade" served to anonymous shoppers is the
        # self-declared sustainability-label class banned by EU ECGT 2024/825 (live
        # 2026-09-27) and an FTC 16 CFR 260.6 general-benefit risk — and it is scrapable
        # straight from this JSON even when the UI hides it. So the graded headline is
        # withheld from the public payload; only the OWNER (authenticated farmer viewing
        # their own production = the dashboard) still receives it. Consumers keep the
        # EVIDENCE the score is built from: event counts, category breakdown,
        # certifications, photos, carbon facts, timeline.
        if not is_owner:
            quick_view = response_data.get("quick_view")
            if isinstance(quick_view, dict):
                quick_view.pop("transparency_score", None)

            transparency_block = response_data.get("transparency")
            if isinstance(transparency_block, dict):
                for graded_key in (
                    "completeness_percentage",
                    "documentation_score",
                    "data_quality_grade",
                    "verification_status",
                ):
                    transparency_block.pop(graded_key, None)

            standard_view = response_data.get("standard_view")
            if isinstance(standard_view, dict):
                details = standard_view.get("transparency_details")
                if isinstance(details, dict):
                    # Drop the rolled-up grade; keep the factual evidence counts
                    # (actual_events / expected_events / category_breakdown).
                    details.pop("completeness_score", None)
                    # Per-category breakdown: keep the factual counts
                    # (actual_count / photo_verified_count / expected_count), strip
                    # the per-category graded "% complete" + status verdict.
                    breakdown = details.get("category_breakdown")
                    if isinstance(breakdown, dict):
                        for category in breakdown.values():
                            if isinstance(category, dict):
                                category.pop("completeness_percentage", None)
                                category.pop("status", None)

            # detailed_view (the "30s deep insights": raw current_score, benchmark
            # level/grade, improvement coaching, verification status) is farmer-facing
            # only — NO consumer component reads it. Drop it wholesale for anonymous
            # so the raw score + grade can't be scraped from this surface.
            response_data.pop("detailed_view", None)

        return Response(response_data, status=status.HTTP_200_OK)

    except (History.DoesNotExist, Http404):
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
    chemical_events = list(history.history_chemicalevent_events.all())
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
        "organic_input_percentage": (
            round((organic_inputs / classified_count * 100)) if classified_count > 0 else None
        ),
    }


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

    if compost:
        methods = sorted({(e.compost_method or "").strip() for e in compost if e.compost_method})
        practices.append({"key": "on_farm_compost", "count": len(compost), "methods": methods})

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


def _get_verification_status(history, transparency_data=None):
    """Get verification status for the production"""

    # Check for various verification indicators
    verifications = {
        "organic_certified": False,
        "third_party_audited": False,
        "blockchain_verified": False,
        "transparency_verified": False,
    }

    # Look for organic certification in events or extra_data
    # BUGFIX: Check that extra_data is a dict before calling .get() to prevent
    # "'str' object has no attribute 'get'" error for malformed data
    if history.extra_data and isinstance(history.extra_data, dict):
        verifications["organic_certified"] = history.extra_data.get("organic_certified", False)
        verifications["blockchain_verified"] = history.extra_data.get("blockchain_verified", False)

    # Check business events for certifications
    from history.models import BusinessEvent

    business_events = BusinessEvent.objects.filter(history=history)

    if business_events.filter(Q(description__icontains="organic") | Q(description__icontains="certified")).exists():
        verifications["organic_certified"] = True

    if business_events.filter(Q(description__icontains="audit") | Q(description__icontains="inspection")).exists():
        verifications["third_party_audited"] = True

    # Transparency verification based on completeness (reuse pre-calculated data if available)
    if transparency_data is None:
        transparency_calculator = TransparencyCalculator()
        transparency_data = transparency_calculator.calculate_transparency_score(history)
    verifications["transparency_verified"] = transparency_data["transparency_percentage"] >= 85

    return verifications


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


def _calculate_data_freshness(history):
    """Calculate how fresh the production data is"""

    if not history.finish_date:
        return "ongoing"

    days_since_completion = (timezone.now().date() - history.finish_date.date()).days

    if days_since_completion <= 30:
        return "very_fresh"
    elif days_since_completion <= 90:
        return "fresh"
    elif days_since_completion <= 365:
        return "recent"
    else:
        return "archived"


@api_view(["GET"])
@permission_classes([AllowAny])
def transparency_explanation(request):
    """
    Consumer education endpoint explaining Trazo's transparency scoring
    Helps consumers understand why transparency percentage matters
    """

    explanation_data = {
        "title": "Understanding Farm Transparency Scores",
        "overview": "Trazo transparency scores show how completely a farm has documented their growing practices. Higher scores mean more complete information.",
        "scoring_levels": {
            "excellent": {
                "range": "90-100%",
                "description": "Complete documentation of farming activities",
                "consumer_message": "You can see the full story of how this food was grown",
            },
            "good": {
                "range": "70-89%",
                "description": "Comprehensive documentation with minor gaps",
                "consumer_message": "Most farming activities are documented and visible",
            },
            "basic": {
                "range": "50-69%",
                "description": "Basic documentation covering main activities",
                "consumer_message": "Key farming activities are documented",
            },
            "limited": {
                "range": "0-49%",
                "description": "Limited documentation available",
                "consumer_message": "Only basic information is available",
            },
        },
        "why_transparency_matters": [
            "See exactly how your food was grown",
            "Verify sustainability claims with real data",
            "Support farmers who practice full transparency",
            "Make informed choices based on complete information",
        ],
        "what_we_track": [
            "Planting and harvesting activities",
            "Fertilizer and chemical applications",
            "Soil management practices",
            "Equipment use and maintenance",
            "Weather and environmental factors",
            "Certifications and inspections",
        ],
        "carbon_vs_transparency": {
            "carbon_score": "Shows environmental impact of production",
            "transparency_score": "Shows how much information is available to verify the carbon score",
            "together": "Both scores help you make informed, sustainable choices",
        },
        # Machine-readable methodology block for API consumers and transparency disclosure.
        "methodology": {
            "description": "Transparency score based on documented agricultural events",
            "data_source": "Farmer-reported data, not independently audited",
            "scoring_method": "Weighted category completeness across 7 event categories",
            "carbon_scope": "Direct operational emissions only (EPA/USDA-sourced factors)",
            "version": "2.0",
            "last_updated": "2026-03-21",
        },
    }

    return Response(explanation_data, status=status.HTTP_200_OK)


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

        history = get_object_or_404(History, **lookup_kwargs)
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
            try:
                current_finalization_hash, current_event_count = _compute_finalization_hash(history)
                if current_finalization_hash == stored_finalization_hash:
                    layer1_status = "intact"
                    layer1_detail = f"All {current_event_count} events match the sealed record."
                else:
                    layer1_status = "tampered"
                    layer1_detail = (
                        "Event data does not match the finalization record. "
                        "Data may have been modified after it was sealed."
                    )
                    logger.warning(
                        "Layer-1 tamper detected for production %s: " "stored=%s, current=%s",
                        history.id,
                        stored_finalization_hash,
                        current_finalization_hash,
                    )
            except Exception as e:
                logger.error("Layer-1 check failed for production %s: %s", history.id, e)
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
                    "status": "pending",
                    "message": (
                        "This production has not yet been submitted to blockchain. "
                        "Blockchain verification occurs in monthly batch cycles."
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

    except (History.DoesNotExist, Http404):
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
