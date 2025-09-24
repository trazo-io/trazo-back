"""
PRODUCT VALIDATION API ENDPOINTS
Ready-to-deploy API endpoints for agricultural product validation.
Integrates with existing Trazo carbon calculation system.
"""

import logging
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.conf import settings

from .services.product_validation_integration import (
    get_product_suggestions_api,
    get_validation_stats_api,
    product_validator
)

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def product_suggestions(request):
    """
    Get product suggestions for autocomplete functionality.
    
    Query Parameters:
        q (str): Partial product name (minimum 2 characters)
        limit (int): Maximum suggestions to return (default: 5, max: 10)
    
    Returns:
        {
            "suggestions": [
                {
                    "name": "Miracle Gro All Purpose Plant Food",
                    "type": "Fertilizer",
                    "type_code": "FE", 
                    "manufacturer": "Scotts",
                    "npk": "24-8-16"
                }
            ],
            "count": 1,
            "query": "miracle"
        }
    """
    query = request.GET.get('q', '').strip()
    limit = min(int(request.GET.get('limit', 5)), 10)
    
    if len(query) < 2:
        return Response({
            "error": "Query must be at least 2 characters long",
            "suggestions": [],
            "count": 0,
            "query": query
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        suggestions = get_product_suggestions_api(query)[:limit]
        
        return Response({
            "suggestions": suggestions,
            "count": len(suggestions),
            "query": query,
            "message": f"Found {len(suggestions)} suggestions for '{query}'"
        })
        
    except Exception as e:
        logger.error(f"Product suggestions API error: {e}")
        return Response({
            "error": "Failed to get product suggestions",
            "suggestions": [],
            "count": 0,
            "query": query
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def validate_product(request):
    """
    Validate a commercial product name against selected chemical type.
    
    Request Body:
        {
            "commercial_name": "Miracle-Gro All Purpose Plant Food",
            "selected_type": "FE",  // FE/PE/FU/HE
            "confidence_threshold": 0.7  // Optional, default 0.7
        }
    
    Returns:
        {
            "validation": {
                "commercial_name": "Miracle-Gro All Purpose Plant Food",
                "correct_type": "FE",
                "confidence": 0.95,
                "type_match": true,
                "warnings": ["ℹ️ NPK Ratio: 24-8-16"],
                "npk_ratio": "24-8-16",
                "manufacturer": "Scotts",
                "active_ingredient": null,
                "recommendation": "Product validated successfully"
            }
        }
    """
    commercial_name = request.data.get('commercial_name', '').strip()
    selected_type = request.data.get('selected_type', '').strip().upper()
    confidence_threshold = float(request.data.get('confidence_threshold', 0.7))
    
    # Validation
    if not commercial_name:
        return Response({
            "error": "commercial_name is required"
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if selected_type not in ['FE', 'PE', 'FU', 'HE']:
        return Response({
            "error": "selected_type must be one of: FE, PE, FU, HE"
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if not 0.0 <= confidence_threshold <= 1.0:
        return Response({
            "error": "confidence_threshold must be between 0.0 and 1.0"
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        # Validate product
        product_match = product_validator.validate_commercial_name(
            commercial_name=commercial_name,
            user_selected_type=selected_type,
            confidence_threshold=confidence_threshold
        )
        
        # Determine recommendation
        if product_match.correct_type == selected_type:
            if product_match.confidence >= confidence_threshold:
                recommendation = "✅ Product validated successfully"
            else:
                recommendation = "⚠️ Product match found but low confidence - verify manually"
        else:
            recommendation = f"❌ Type mismatch detected - should be {_get_type_name(product_match.correct_type)}"
        
        return Response({
            "validation": {
                "commercial_name": product_match.commercial_name,
                "correct_type": product_match.correct_type,
                "confidence": round(product_match.confidence, 3),
                "type_match": product_match.correct_type == selected_type,
                "warnings": product_match.warnings,
                "npk_ratio": product_match.npk_ratio,
                "manufacturer": product_match.manufacturer,
                "active_ingredient": product_match.active_ingredient,
                "recommendation": recommendation,
                "suggested_npk": _get_suggested_npk(product_match) if selected_type == 'FE' else None
            }
        })
        
    except Exception as e:
        logger.error(f"Product validation API error: {e}")
        return Response({
            "error": "Failed to validate product",
            "details": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def validation_stats(request):
    """
    Get product validation statistics for admin/monitoring.
    
    Returns:
        {
            "stats": {
                "total_products": 25,
                "fertilizers": 10,
                "pesticides": 5,
                "fungicides": 5,
                "herbicides": 5,
                "coverage": "Top 25 most common agricultural products"
            },
            "database_info": {
                "version": "1.0.0",
                "last_updated": "2025-01-15",
                "focus": "Most common products to maximize impact"
            }
        }
    """
    try:
        stats = get_validation_stats_api()
        
        return Response({
            "stats": stats,
            "database_info": {
                "version": "1.0.0",
                "last_updated": "2025-01-15",
                "focus": "Most common products to maximize impact",
                "accuracy_target": ">85% for common agricultural products"
            }
        })
        
    except Exception as e:
        logger.error(f"Validation stats API error: {e}")
        return Response({
            "error": "Failed to get validation statistics"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def product_database(request):
    """
    Get the complete product database for admin purposes.
    Useful for debugging and expanding the database.
    
    Returns:
        {
            "products": {
                "fertilizers": [...],
                "pesticides": [...],
                "fungicides": [...], 
                "herbicides": [...]
            },
            "total_count": 25
        }
    """
    try:
        # Only allow admin users to see full database
        if not request.user.is_staff:
            return Response({
                "error": "Admin access required"
            }, status=status.HTTP_403_FORBIDDEN)
        
        products_by_type = {"fertilizers": [], "pesticides": [], "fungicides": [], "herbicides": []}
        
        for product_key, product_data in product_validator.PRODUCT_DATABASE.items():
            product_info = {
                "key": product_key,
                "name": product_key.replace("-", " ").title(),
                "type": product_data["type"],
                "variants": product_data.get("variants", []),
                "npk": product_data.get("npk"),
                "manufacturer": product_data.get("manufacturer"),
                "active_ingredient": product_data.get("active_ingredient"),
                "common_mistakes": product_data.get("common_mistakes", [])
            }
            
            if product_data["type"] == "FE":
                products_by_type["fertilizers"].append(product_info)
            elif product_data["type"] == "PE":
                products_by_type["pesticides"].append(product_info)
            elif product_data["type"] == "FU":
                products_by_type["fungicides"].append(product_info)
            elif product_data["type"] == "HE":
                products_by_type["herbicides"].append(product_info)
        
        return Response({
            "products": products_by_type,
            "total_count": sum(len(products) for products in products_by_type.values()),
            "database_version": "1.0.0"
        })
        
    except Exception as e:
        logger.error(f"Product database API error: {e}")
        return Response({
            "error": "Failed to get product database"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Helper functions
def _get_type_name(type_code: str) -> str:
    """Convert type code to human-readable name"""
    type_names = {
        "FE": "Fertilizer",
        "PE": "Pesticide",
        "FU": "Fungicide", 
        "HE": "Herbicide"
    }
    return type_names.get(type_code, type_code)


def _get_suggested_npk(product_match) -> Optional[dict]:
    """Get suggested NPK values for fertilizers"""
    if product_match.npk_ratio and product_match.confidence > 0.7:
        try:
            npk_parts = product_match.npk_ratio.split('-')
            if len(npk_parts) == 3:
                return {
                    "nitrogen": float(npk_parts[0]),
                    "phosphorus": float(npk_parts[1]),
                    "potassium": float(npk_parts[2]),
                    "ratio": product_match.npk_ratio,
                    "confidence": product_match.confidence
                }
        except (ValueError, IndexError):
            pass
    return None