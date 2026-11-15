"""
Security views for QR code verification and security endpoints
"""

import json
import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from backend.security.qr_security import get_qr_security_manager
from history.models import Production

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_qr_code(request):
    """
    Verify a QR code URL and return security information

    POST /api/security/verify-qr/
    {
        "url": "https://consumer.trazo.io/production/123?p=...&s=..."
    }
    """
    try:
        data = json.loads(request.body)
        url = data.get("url")

        if not url:
            return Response({"error": "URL is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Verify the QR code
        is_valid, payload, error_message = get_qr_security_manager().verify_qr_url(url)

        # Get QR metadata
        metadata = get_qr_security_manager().get_qr_metadata(url)

        response_data = {
            "valid": is_valid,
            "error": error_message,
            "metadata": metadata,
            "security_level": "high" if is_valid and metadata.get("is_secure") else "low",
        }

        if is_valid and payload:
            # Get production information if available
            production_id = payload.get("id")
            if production_id:
                try:
                    production = Production.objects.get(id=production_id, published=True)
                    response_data["production"] = {
                        "id": str(production.public_id),
                        "name": production.name,
                        "verified": True,
                        "reputation": production.reputation,
                    }
                except Production.DoesNotExist:
                    response_data["production"] = {
                        "id": production_id,
                        "verified": False,
                        "error": "Production not found or not published",
                    }

        return Response(response_data, status=status.HTTP_200_OK)

    except json.JSONDecodeError:
        return Response({"error": "Invalid JSON"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"QR verification error: {e}")
        return Response({"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
