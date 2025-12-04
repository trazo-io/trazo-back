"""
Trazo Consumer Transparency API Views
Provides transparency-first data for QR scanning experience
Eliminates competitive carbon ranking to solve farmer incentive problems

Following Trazo's main goal: Authentic transparency leadership
"""

import logging

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from carbon.services.calculator_service import CarbonCalculatorService

from .models import History, HistoryScan
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
        # Get production with related data (optimized query)
        history = get_object_or_404(
            History.objects.select_related("product", "parcel__establishment__company", "parcel__establishment"),
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
        history = get_object_or_404(
            History.objects.select_related("product", "parcel__establishment"), id=production_id, published=True
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
    if history.extra_data:
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
