"""
Mock Transparency Endpoints for Frontend Testing
Temporary endpoints that return test data without database
"""

from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def mock_transparency_detail(request, production_id):
    """Mock transparency detail endpoint for testing"""

    # Return test data for any production ID
    response_data = {
        "quick_view": {
            "farm_name": "Green Valley Test Farm",
            "product_name": "Organic Avocados",
            "transparency_score": {"percentage": 85, "message": "Comprehensive farm record", "status": "good"},
            "carbon_impact": {"kg_per_kg": 1.2, "total_emissions": 2400, "unit": "kg CO₂ per kg product"},
        },
        "standard_view": {
            "transparency_details": {
                "completeness_score": 85,
                "actual_events": 42,
                "expected_events": 50,
                "farming_approach": "organic",
                "category_breakdown": {
                    "soil_preparation": {
                        "actual_count": 8,
                        "expected_count": 10,
                        "completeness_percentage": 80,
                        "status": "good",
                    },
                    "planting": {
                        "actual_count": 10,
                        "expected_count": 10,
                        "completeness_percentage": 100,
                        "status": "excellent",
                    },
                    "fertilization": {
                        "actual_count": 12,
                        "expected_count": 15,
                        "completeness_percentage": 80,
                        "status": "good",
                    },
                },
            },
            "carbon_details": {
                "total_emissions": 2400,
                "breakdown": {"fertilizers": 800, "equipment": 600, "transport": 500, "processing": 500},
                "calculation_date": timezone.now().isoformat(),
            },
            "farm_details": {
                "name": "Green Valley Test Farm",
                "location": "California, USA",
                "total_area": 50,
                "country": "USA",
            },
            "product_details": {
                "name": "Organic Avocados",
                "production_name": f"Test Production {production_id}",
                "start_date": "2025-01-01",
                "end_date": "2025-06-30",
            },
        },
        "detailed_view": {
            "transparency_insights": {
                "current_score": 85,
                "recommendations": [
                    "Add water usage records for 15% improvement",
                    "Document pest management activities",
                    "Include soil testing results",
                ],
                "missing_categories": [
                    {
                        "category": "water_management",
                        "status": "missing",
                        "suggestion": "Track irrigation schedules and water usage",
                    }
                ],
                "strong_categories": ["planting", "harvesting", "packaging"],
            },
            "benchmark_comparison": {
                "benchmark_level": "good",
                "message": "Above industry standards",
                "benchmarks": {
                    "industry_minimum": 50,
                    "good_practice": 70,
                    "excellent_practice": 90,
                    "certification_standard": 95,
                },
                "current_score": 85,
                "next_target": {"target_score": 90, "target_name": "Excellent Practice", "points_needed": 5},
            },
            "verification_status": {
                "organic_certified": True,
                "third_party_audited": False,
                "blockchain_verified": True,
                "transparency_verified": True,
            },
            "data_quality_indicators": {
                "last_updated": timezone.now().isoformat(),
                "data_freshness": "very_fresh",
                "completeness_trend": "improving",
            },
        },
        "api_version": "2.0-mock",
        "response_timestamp": timezone.now().isoformat(),
        "trazo_transparency_certified": True,
        "transparency": {"completeness_percentage": 85, "data_quality": "good", "verification_status": "verified"},
        "carbon_impact": {"kg_per_kg": 1.2, "total_emissions": 2400, "unit": "kg CO₂ per kg product"},
    }

    return Response(response_data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
def mock_transparency_summary(request, production_id):
    """Mock transparency summary endpoint for testing"""

    # Return test data for any production ID
    response_data = {
        "farm_name": "Green Valley Test Farm",
        "product_name": "Organic Avocados",
        "transparency": {"percentage": 85, "message": "Comprehensive farm record", "level": "good"},
        "carbon": {"kg_per_kg": 1.2},
        "scan_timestamp": timezone.now().isoformat(),
        "transparency_score": {"percentage": 85, "message": "Comprehensive farm record", "status": "good"},
        "carbon_score": {"kg_per_kg": 1.2, "unit": "kg CO₂"},
    }

    return Response(response_data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
def mock_transparency_explanation(request):
    """Mock transparency explanation endpoint"""

    response_data = {
        "title": "Understanding Transparency Scoring",
        "overview": "Transparency scoring rewards complete and honest farm record keeping, not competitive carbon rankings.",
        "scoring_levels": {
            "excellent": {
                "range": "90-100%",
                "description": "Complete farm transparency",
                "consumer_message": "This farm provides full visibility into their practices",
            },
            "good": {
                "range": "70-89%",
                "description": "Comprehensive farm record",
                "consumer_message": "This farm shares most of their farming practices",
            },
            "basic": {
                "range": "50-69%",
                "description": "Basic farm information",
                "consumer_message": "This farm provides essential information",
            },
            "limited": {
                "range": "0-49%",
                "description": "Limited information",
                "consumer_message": "More information needed from this farm",
            },
        },
        "why_transparency_matters": [
            "Builds consumer trust through honest reporting",
            "Rewards farmers for complete records, not gaming",
            "Enables informed purchasing decisions",
            "Supports authentic sustainability efforts",
        ],
        "what_we_track": [
            "Soil preparation and management",
            "Planting and growing practices",
            "Fertilization and chemical use",
            "Water management and irrigation",
            "Harvesting and processing",
            "Transportation and storage",
        ],
        "carbon_vs_transparency": {
            "carbon_score": "Measures environmental impact in kg CO₂ per kg product",
            "transparency_score": "Measures completeness of farm record keeping",
            "together": "Complete transparency enables accurate carbon tracking",
        },
    }

    return Response(response_data, status=status.HTTP_200_OK)
