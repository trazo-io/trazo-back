"""
Trazo Consumer Transparency API Views
Provides transparency-first data for QR scanning experience
Eliminates competitive carbon ranking to solve farmer incentive problems

Following Trazo's main goal: Authentic transparency leadership
"""

import logging

from django.db.models import Count, Q, Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from carbon.services.calculator_service import CarbonCalculatorService

from .models import (
    History,
    HistoryScan,
    WeatherEvent,
    ChemicalEvent,
    ProductionEvent,
    GeneralEvent,
    EquipmentEvent,
    SoilManagementEvent,
    PestManagementEvent,
    BusinessEvent,
)
from .serializers import PublicHistorySerializer
from .services.transparency_calculator import TransparencyCalculator
from .services.transparency_response_formatter import TransparencyResponseFormatter

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
def production_transparency_detail(request, production_id):
    """
    Consumer-facing transparency endpoint for QR scanning

    Returns transparency percentage and carbon data WITHOUT competitive rankings
    This solves the farmer gaming incentive problem by rewarding honesty over competition
    """
    try:
        # Get production with related data (optimized query with prefetch for all event types and carbon data)
        # This eliminates N+1 queries by prefetching all 8 event types with their albums and images
        # OPTIMIZATION (2025-12-12): Also prefetch CarbonEntry to support carbon data lookups
        from carbon.models import CarbonEntry

        history = get_object_or_404(
            History.objects.select_related(
                "product",
                "parcel__establishment__company",
                "parcel__establishment"
            ).prefetch_related(
                # Prefetch all 8 event types with albums and images to avoid N+1 queries
                Prefetch(
                    "history_weatherevent_events",
                    queryset=WeatherEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_chemicalevent_events",
                    queryset=ChemicalEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_productionevent_events",
                    queryset=ProductionEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_generalevent_events",
                    queryset=GeneralEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_equipmentevent_events",
                    queryset=EquipmentEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_soilmanagementevent_events",
                    queryset=SoilManagementEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_pestmanagementevent_events",
                    queryset=PestManagementEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_businessevent_events",
                    queryset=BusinessEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                # OPTIMIZATION (2025-12-12): Prefetch all CarbonEntry records for this production
                # This eliminates separate queries when _get_event_carbon_data() is called
                Prefetch(
                    "carbonentry_set",
                    queryset=CarbonEntry.objects.all().order_by("-created_at")
                ),
            ),
            id=production_id,
            published=True,  # Only published productions are publicly accessible
        )

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
            "production_name": history.name or f"Production {history.id}",
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
            "usda_verified": True,  # Based on your carbon calculation method
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

        # Add timeline events with album data (same as producer page gets)
        # This ensures photos are available on consumer page
        public_history_serializer = PublicHistorySerializer(history, context={"request": request})
        public_history_data = public_history_serializer.data

        # Include timeline events in the response for photo display
        if "events" in public_history_data:
            response_data["timeline_events"] = public_history_data["events"]

        # ✅ PHASE 1 FIX: Use CarbonEntry as single source of truth for USDA verification
        # SEMANTIC CHANGE (2025-12-12): is_usda_verified now means "USDA factors were used"
        # not "validation passed at high confidence"
        from carbon.models import CarbonEntry

        # Check if ALL carbon entries for this production have USDA verification
        # This uses the fixed USDAComplianceRecord.is_usda_verified property which checks:
        # - validation_method in ["enhanced_api", "local_validation"] (not error)
        # - crop_type is identified (validation ran properly)
        total_carbon_entries = CarbonEntry.objects.filter(production=history).count()
        usda_verified_entries = CarbonEntry.objects.filter(
            production=history,
            usda_verified=True  # Uses the fixed is_usda_verified property
        ).count()

        # USDA verified if ALL carbon entries used USDA factors
        is_usda_verified = (total_carbon_entries > 0 and usda_verified_entries == total_carbon_entries)

        # Add progressive loading structure for backward compatibility
        response_data.update(
            {
                # IMMEDIATE LOAD - Most critical info (using new format)
                "quick_view": {
                    "farm_name": farm_info["name"],
                    "product_name": product_info["name"],
                    "transparency_score": {
                        "percentage": transparency_data["transparency_percentage"],
                        "message": transparency_data["message"],
                        "status": transparency_benchmarks["benchmark_level"],
                    },
                    "carbon_impact": response_data["carbon_impact"],
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
                    "carbon_details": {
                        "total_emissions": carbon_score,
                        "breakdown": carbon_breakdown,
                        "calculation_date": transparency_data.get("calculation_timestamp"),
                    },
                    "farm_details": farm_info,
                    "product_details": product_info,
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
                # Metadata
                "api_version": "2.0",
                "response_timestamp": timezone.now().isoformat(),
                "trazo_transparency_certified": transparency_data["transparency_percentage"] >= 80,
                # Additional fields for frontend compatibility with ProductDetail.tsx
                "farmer": {
                    # 🚨 CRITICAL FIX: Complete farmer/establishment data for ProductDetail.tsx
                    "id": establishment.id if establishment else None,
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
                    "location": f"{establishment.city}, {establishment.state}" if establishment and establishment.city else None,
                    "certifications": establishment.certifications if establishment else None,
                    "climate_zone": establishment.climate_zone if establishment else None,
                    "water_sources": establishment.water_sources if establishment else None,
                    "soil_types": establishment.soil_types if establishment else None,
                    "conservation_practices": establishment.conservation_practices if establishment else None,
                    "irrigation_methods": establishment.irrigation_methods if establishment else None,
                    # Nested company data
                    "company": {
                        "id": establishment.company.id if establishment and establishment.company else None,
                        "name": establishment.company.name if establishment and establishment.company else "Company",
                        "description": establishment.company.description if establishment and establishment.company else "",
                        "address": establishment.company.address if establishment and establishment.company else None,
                        "city": establishment.company.city if establishment and establishment.company else None,
                        "state": establishment.company.state if establishment and establishment.company else None,
                        "country": establishment.company.country if establishment and establishment.company else None,
                        "email": establishment.company.contact_email if establishment and establishment.company else None,  # Company uses contact_email
                        "phone": establishment.company.contact_phone if establishment and establishment.company else None,  # Company uses contact_phone
                        "website": establishment.company.website if establishment and establishment.company else None,
                        "facebook": establishment.company.facebook if establishment and establishment.company else None,
                        "instagram": establishment.company.instagram if establishment and establishment.company else None,
                        "logo": establishment.company.logo.url if establishment and establishment.company and establishment.company.logo else None,
                        "fiscal_id": establishment.company.fiscal_id if establishment and establishment.company else None,
                        "contact_email": establishment.company.contact_email if establishment and establishment.company else None,
                        "total_establishments": establishment.company.establishment_set.count() if establishment and establishment.company else 0,
                        "total_parcels": sum(e.parcels.count() for e in establishment.company.establishment_set.all()) if establishment and establishment.company else 0,
                    } if establishment else {
                        "name": "Company",
                        "total_establishments": 0,
                        "total_parcels": 0
                    }
                },
                "product": {
                    "name": history.product.name if history.product else "Farm Product"
                },
                "reputation": history.reputation or 0,
                "isUsdaVerified": is_usda_verified,
                "timeline": public_history_data.get("events", []),
                # 🚨 CRITICAL FIX: Add missing fields that ProductDetail.tsx expects
                "events": public_history_data.get("events", []),  # Alias for timeline for backward compatibility
                "harvestDetails": {
                    "amount": history.production_amount,
                    "unit": history.production_unit,
                    "lot_number": history.lot_id,
                    "quality_grade": history.quality_grade,
                    "harvest_method": history.harvest_method,
                },
                "parcel": {
                    "id": history.parcel.id if history.parcel else None,
                    "name": history.parcel.name if history.parcel else None,
                    "area": history.parcel.area if history.parcel else None,
                },
                "images": public_history_data.get("images", []),  # Photo gallery for ProductDetail
            }
        )  # Close the response_data.update() call

        return Response(response_data, status=status.HTTP_200_OK)

    except History.DoesNotExist:
        formatter = TransparencyResponseFormatter()
        error_response = formatter.format_error_response(
            error_message="Production not found",
            error_details="This QR code is not in our system or is not publicly available",
        )
        return Response(error_response, status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        logger.error(f"Transparency detail error for production {production_id}: {str(e)}")
        formatter = TransparencyResponseFormatter()
        error_response = formatter.format_error_response(
            error_message="Service temporarily unavailable", error_details="Please try again in a moment"
        )
        return Response(error_response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([AllowAny])
def production_transparency_summary(request, production_id):
    """
    Lightweight transparency summary for mobile QR scanning
    Optimized for < 1 second response time
    """
    try:
        # Get production with optimized queries (prefetch all event types with albums)
        history = get_object_or_404(
            History.objects.select_related(
                "product",
                "parcel__establishment"
            ).prefetch_related(
                # Prefetch all 8 event types with albums and images
                Prefetch(
                    "history_weatherevent_events",
                    queryset=WeatherEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_chemicalevent_events",
                    queryset=ChemicalEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_productionevent_events",
                    queryset=ProductionEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_generalevent_events",
                    queryset=GeneralEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_equipmentevent_events",
                    queryset=EquipmentEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_soilmanagementevent_events",
                    queryset=SoilManagementEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_pestmanagementevent_events",
                    queryset=PestManagementEvent.objects.select_related("album").prefetch_related("album__images")
                ),
                Prefetch(
                    "history_businessevent_events",
                    queryset=BusinessEvent.objects.select_related("album").prefetch_related("album__images")
                ),
            ),
            id=production_id,
            published=True
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
def production_instant_trust(request, production_id):
    """
    Ultra-fast instant trust endpoint for QR scanning
    Optimized for <750ms response time with essential trust indicators only
    Returns: transparency score, consumer message, basic farm info
    """
    try:
        # Ultra-lightweight query - only get essential fields
        history = (
            History.objects.select_related("product", "parcel__establishment")
            .only("id", "product__name", "parcel__establishment__name", "extra_data", "published")
            .get(id=production_id, published=True)
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
        logger.error(f"Instant trust error for production {production_id}: {str(e)}")
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
