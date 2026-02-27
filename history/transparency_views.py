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
    HistoryScan,
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
def production_transparency_detail(request, production_public_id=None, production_id=None):
    """
    Consumer-facing transparency endpoint for QR scanning

    Returns transparency percentage and carbon data WITHOUT competitive rankings
    This solves the farmer gaming incentive problem by rewarding honesty over competition

    Accepts either UUID (production_public_id) or legacy integer (production_id).
    """
    try:
        # Build lookup filter: UUID (preferred) or legacy integer
        lookup_kwargs = {}
        if production_public_id is not None:
            lookup_kwargs["public_id"] = production_public_id
        elif production_id is not None:
            lookup_kwargs["id"] = production_id
        else:
            return Response({"error": "Production identifier required"}, status=status.HTTP_400_BAD_REQUEST)

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
            carbon_score = 0
            carbon_breakdown = {}

        # Get benchmark comparison (ABSOLUTE standards, not competitive rankings)
        transparency_benchmarks = transparency_calculator.compare_with_benchmarks(history)

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

        # Product information
        product_info = {
            "name": history.product.name if history.product else "Farm Product",
            "production_name": history.name or f"Production {history.public_id}",
            "start_date": history.start_date.isoformat() if history.start_date else None,
            "end_date": history.finish_date.isoformat() if history.finish_date else None,
        }

        # Track scan for analytics (but don't return scan data to user)
        try:
            # Simple scan tracking without heavy privacy processing
            HistoryScan.objects.create(
                history=history,
                user=request.user if request.user.is_authenticated else None,
                date=timezone.now(),
                scan_type="transparency_api",
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )
        except Exception as e:
            # Don't fail the whole request if scan tracking fails
            logger.warning(f"Scan tracking failed: {str(e)}")

        # Use standardized transparency response formatter
        formatter = TransparencyResponseFormatter()

        # Prepare data for formatter
        carbon_data_formatted = {
            "total_co2_kg_per_kg": carbon_score,
            "total_emissions": carbon_breakdown.get("total_emissions", 0),
            "total_offsets": carbon_breakdown.get("total_offsets", 0),
            "net_footprint": carbon_score,  # This should be calculated properly
            "usda_factors_used": True,  # Based on your carbon calculation method
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

        # Get standardized response
        response_data = formatter.format_qr_response(
            production=history,
            carbon_data=carbon_data_formatted,
            transparency_data=transparency_data_formatted,
            blockchain_verification={"verified": True},  # You can implement proper blockchain checking
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

        # ✅ PHASE 1 FIX: Use CarbonEntry as single source of truth for USDA verification
        # SEMANTIC CHANGE (2025-12-12): is_usda_verified now means "USDA factors were used"
        # not "validation passed at high confidence"
        from carbon.models import CarbonEntry

        # Check if ALL carbon entries for this production have USDA verification
        # This uses the fixed USDAComplianceRecord.is_usda_verified property which checks:
        # - validation_method in ["enhanced_api", "local_validation"] (not error)
        # - crop_type is identified (validation ran properly)
        total_carbon_entries = CarbonEntry.objects.filter(production=history).count()
        usda_factors_based_entries = CarbonEntry.objects.filter(
            production=history, usda_factors_based=True
        ).count()

        # USDA verified if ALL carbon entries used USDA factors
        is_usda_verified = total_carbon_entries > 0 and usda_factors_based_entries == total_carbon_entries

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
                },
                # DETAILED LOAD (30+ seconds) - Deep insights
                "detailed_view": {
                    "transparency_insights": transparency_calculator.get_transparency_insights(history),
                    "benchmark_comparison": transparency_benchmarks,
                    "improvement_suggestions": transparency_benchmarks.get("next_target", {}),
                    "verification_status": _get_verification_status(history),
                    "data_quality_indicators": {
                        "last_updated": transparency_data.get("calculation_timestamp"),
                        "data_freshness": _calculate_data_freshness(history),
                        "completeness_trend": "improving",  # Could be calculated from historical data
                    },
                },
                # Blockchain verification data for consumer-facing badge
                "blockchain_verification": _get_blockchain_verification_data(history),
                # Metadata
                "api_version": "2.0",
                "response_timestamp": timezone.now().isoformat(),
                # Additional fields for frontend compatibility with ProductDetail.tsx
                "farmer": {
                    # 🚨 CRITICAL FIX: Complete farmer/establishment data for ProductDetail.tsx
                    "id": str(establishment.public_id) if establishment else None,
                    "name": establishment.name if establishment else "Farm",
                    "description": establishment.description if establishment else "",
                    "address": establishment.address if establishment else None,
                    "city": establishment.city if establishment else None,
                    "state": establishment.state if establishment else None,
                    "country": establishment.country if establishment else None,
                    "zone": establishment.zone if establishment else None,
                    "latitude": establishment.latitude if establishment else None,
                    "longitude": establishment.longitude if establishment else None,
                    "contact_person": establishment.contact_person if establishment else None,
                    "contact_phone": establishment.contact_phone if establishment else None,
                    "contact_email": establishment.contact_email if establishment else None,
                    "email": establishment.contact_email if establishment else None,  # Use contact_email field
                    "phone": establishment.contact_phone if establishment else None,  # Use contact_phone field
                    "zip_code": establishment.zip_code if establishment else None,
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
                    "certifications": establishment.certifications if establishment else None,
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
                            "address": (
                                establishment.company.address if establishment and establishment.company else None
                            ),
                            "city": establishment.company.city if establishment and establishment.company else None,
                            "state": establishment.company.state if establishment and establishment.company else None,
                            "country": (
                                establishment.company.country if establishment and establishment.company else None
                            ),
                            "email": (
                                establishment.company.contact_email if establishment and establishment.company else None
                            ),  # Company uses contact_email
                            "phone": (
                                establishment.company.contact_phone if establishment and establishment.company else None
                            ),  # Company uses contact_phone
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
                            "fiscal_id": (
                                establishment.company.fiscal_id if establishment and establishment.company else None
                            ),
                            "contact_email": (
                                establishment.company.contact_email if establishment and establishment.company else None
                            ),
                            "total_establishments": (
                                establishment.company.establishment_set.count()
                                if establishment and establishment.company
                                else 0
                            ),
                            "total_parcels": (
                                sum(e.parcels.count() for e in establishment.company.establishment_set.all())
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
                "isUsdaVerified": is_usda_verified,
                "timeline": public_history_data.get("events", []),
                "harvestDetails": {
                    "amount": history.production_amount,
                    "unit": history.production_unit,
                    "lot_number": history.lot_id,
                    "quality_grade": history.quality_grade,
                    "harvest_method": history.harvest_method,
                },
                "parcel": {
                    "name": history.parcel.name if history.parcel else None,
                    "area": history.parcel.area if history.parcel else None,
                },
                "images": public_history_data.get("images", []),  # Photo gallery for ProductDetail
            }
        )  # Close the response_data.update() call

        return Response(response_data, status=status.HTTP_200_OK)

    except (History.DoesNotExist, Http404):
        formatter = TransparencyResponseFormatter()
        error_response = formatter.format_error_response(
            error_message="Production not found",
            error_details="This QR code is not in our system or is not publicly available",
        )
        return Response(error_response, status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        lookup_ref = production_public_id or production_id
        logger.error(f"Transparency detail error for production {lookup_ref}: {str(e)}")
        formatter = TransparencyResponseFormatter()
        error_response = formatter.format_error_response(
            error_message="Service temporarily unavailable", error_details="Please try again in a moment"
        )
        return Response(error_response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([AllowAny])
def production_transparency_summary(request, production_public_id=None, production_id=None):
    """
    Lightweight transparency summary for mobile QR scanning
    Optimized for < 1 second response time

    Accepts either UUID (production_public_id) or legacy integer (production_id).
    """
    try:
        # Build lookup filter: UUID (preferred) or legacy integer
        lookup_kwargs = {"published": True}
        if production_public_id is not None:
            lookup_kwargs["public_id"] = production_public_id
        elif production_id is not None:
            lookup_kwargs["id"] = production_id
        else:
            return Response({"error": "Production identifier required"}, status=status.HTTP_400_BAD_REQUEST)

        # Get production with optimized queries (prefetch all event types with albums)
        history = get_object_or_404(
            History.objects.select_related("product", "parcel__establishment").prefetch_related(
                # Prefetch all 8 event types with albums and images
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
            ),
            **lookup_kwargs,
        )

        # Quick transparency calculation (cached if possible)
        transparency_calculator = TransparencyCalculator()
        transparency_data = transparency_calculator.calculate_transparency_score(history)

        # Minimal carbon data (existing calculation)
        try:
            carbon_service = CarbonCalculatorService()
            carbon_result = carbon_service.calculate_production_carbon(history.id)
            carbon_score = carbon_result.get("total_co2_kg_per_kg", 0)
        except:
            carbon_score = 0

        # Use standardized transparency formatter for mobile
        formatter = TransparencyResponseFormatter()

        # Prepare minimal carbon data for quick response
        minimal_carbon_data = {"kg_per_kg": carbon_score}

        # Get standardized quick response
        response_data = formatter.format_quick_response(production=history, minimal_carbon_data=minimal_carbon_data)

        # Add farm and product context for backward compatibility
        response_data.update(
            {
                "farm_name": history.parcel.establishment.name if history.parcel else "Farm",
                "product_name": history.product.name if history.product else "Farm Product",
                "transparency_level": (
                    "excellent"
                    if transparency_data["transparency_percentage"] >= 90
                    else "good" if transparency_data["transparency_percentage"] >= 70 else "basic"
                ),
            }
        )

        return Response(response_data, status=status.HTTP_200_OK)

    except History.DoesNotExist:
        formatter = TransparencyResponseFormatter()
        error_response = formatter.format_error_response("Production not found")
        return Response(error_response, status=status.HTTP_404_NOT_FOUND)


@api_view(["GET"])
@permission_classes([AllowAny])
def production_instant_trust(request, production_public_id=None, production_id=None):
    """
    Ultra-fast instant trust endpoint for QR scanning
    Optimized for <750ms response time with essential trust indicators only
    Returns: transparency score, consumer message, basic farm info

    Accepts either UUID (production_public_id) or legacy integer (production_id).
    """
    try:
        # Build lookup filter: UUID (preferred) or legacy integer
        lookup_kwargs = {"published": True}
        if production_public_id is not None:
            lookup_kwargs["public_id"] = production_public_id
        elif production_id is not None:
            lookup_kwargs["id"] = production_id
        else:
            return Response(
                {"success": False, "error": "missing_id", "message": "Production identifier required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Ultra-lightweight query - only get essential fields
        history = (
            History.objects.select_related("product", "parcel__establishment")
            .only("id", "public_id", "product__name", "parcel__establishment__name", "extra_data", "published")
            .get(**lookup_kwargs)
        )

        # Fast transparency calculation
        transparency_calculator = TransparencyCalculator()
        transparency_data = transparency_calculator.calculate_transparency_score(history)

        # Build instant trust response with new consumer-friendly messaging
        instant_trust_data = {
            "success": True,
            "transparency_percentage": transparency_data["transparency_percentage"],
            "consumer_summary": transparency_data.get(
                "consumer_summary",
                f"This food has {transparency_data['transparency_percentage']:.0f}% transparency with {transparency_data['actual_event_count']} documented farming practices",
            ),
            "actual_event_count": transparency_data["actual_event_count"],
            "expected_event_count": transparency_data["expected_event_count"],
            "farm_name": history.parcel.establishment.name if history.parcel else "Verified Farm",
            "product_name": history.product.name if history.product else "Farm Product",
            "trust_level": _get_trust_level(transparency_data["transparency_percentage"]),
            "is_verified": transparency_data["transparency_percentage"] >= 70,
            "instant_trust_message": _get_instant_trust_message(transparency_data),
            "response_time": "instant",  # Flag for frontend optimization
            "api_version": "2.1",
        }

        return Response(instant_trust_data, status=status.HTTP_200_OK)

    except History.DoesNotExist:
        return Response(
            {
                "success": False,
                "error": "production_not_found",
                "message": "This product was not found in our transparency system",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception as e:
        lookup_ref = production_public_id or production_id
        logger.error(f"Instant trust error for production {lookup_ref}: {str(e)}")
        return Response(
            {"success": False, "error": "service_error", "message": "Unable to load trust indicators at this time"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _get_trust_level(transparency_percentage):
    """Get consumer-friendly trust level for instant display"""
    if transparency_percentage >= 95:
        return "complete"
    elif transparency_percentage >= 85:
        return "excellent"
    elif transparency_percentage >= 70:
        return "good"
    elif transparency_percentage >= 50:
        return "basic"
    else:
        return "limited"


def _get_instant_trust_message(transparency_data):
    """Generate instant trust message for immediate consumer confidence"""
    score = transparency_data["transparency_percentage"]
    practices = transparency_data["actual_event_count"]

    if score >= 95:
        return f"Complete farming transparency with {practices} documented practices"
    elif score >= 85:
        return f"Excellent transparency with {practices} farming practices documented"
    elif score >= 70:
        return f"Good transparency - {practices} farming practices shared"
    elif score >= 50:
        return f"Basic transparency with {practices} practices documented"
    else:
        return f"Building transparency - {practices} practices currently documented"


def _get_verification_status(history):
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

    # Transparency verification based on completeness
    transparency_calculator = TransparencyCalculator()
    transparency_data = transparency_calculator.calculate_transparency_score(history)
    verifications["transparency_verified"] = transparency_data["transparency_percentage"] >= 85

    return verifications


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

    Uses the same algorithm as product/views.py _store_finalization_hash()
    so the result can be compared against the stored hash to detect tampering.
    """
    import hashlib
    import json

    events = history.get_events()  # Sorted by index
    event_data = json.dumps(events, sort_keys=True, default=str, separators=(",", ":"))

    try:
        from web3 import Web3

        raw_hex = Web3.keccak(text=event_data).hex()
        return raw_hex.removeprefix("0x"), len(events)
    except ImportError:
        return hashlib.sha256(event_data.encode()).hexdigest(), len(events)


def _recompute_production_data_hash(history, finalization_hash):
    """Rebuild the raw_data dict exactly as the batch task (carbon/tasks.py) did,
    and hash it with keccak256.  The result should match the on-chain dataHash
    if no data has been modified since blockchain submission.

    IMPORTANT: The field names, order, and serialisation must stay in sync with
    carbon/tasks.py batch_submit_monthly_summaries().  If the batch task changes
    its raw_data schema, this function MUST be updated to match.
    """
    import hashlib
    import json

    from django.db.models import Sum

    try:
        from carbon.models import CarbonEntry

        carbon_entries = CarbonEntry.objects.filter(production=history)
        total_co2e = float(carbon_entries.aggregate(total=Sum("co2e_amount"))["total"] or 0)
        entry_count = carbon_entries.count()

        extra = history.extra_data if isinstance(history.extra_data, dict) else {}
        company_id = None
        if history.parcel and history.parcel.establishment:
            company_id = history.parcel.establishment.company_id

        finalization_event_count = extra.get("finalization_event_count", 0)

        # Must match carbon/tasks.py raw_data exactly
        raw_data = {
            "production_id": history.id,
            "company_id": company_id,
            "start_date": (history.start_date.isoformat() if history.start_date else None),
            "finish_date": (history.finish_date.isoformat() if history.finish_date else None),
            "total_co2e": total_co2e,
            "entry_count": entry_count,
            "entries": list(carbon_entries.values("id", "co2e_amount", "type", "timestamp")),
            "finalization_hash": finalization_hash,
            "finalization_event_count": finalization_event_count,
        }

        sorted_raw = json.dumps(raw_data, sort_keys=True, default=str)

        try:
            from web3 import Web3

            raw_hex = Web3.keccak(text=sorted_raw).hex()
            return raw_hex.removeprefix("0x")
        except ImportError:
            return hashlib.sha256(sorted_raw.encode()).hexdigest()

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
    }

    return Response(explanation_data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
def verify_blockchain(request, production_public_id=None, production_id=None):
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
        lookup_kwargs = {"published": True}
        if production_public_id is not None:
            lookup_kwargs["public_id"] = production_public_id
        elif production_id is not None:
            lookup_kwargs["id"] = production_id
        else:
            return Response(
                {"error": "Production identifier required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
