"""
Security views for QR code verification and security endpoints
"""

import json
import logging

from django.http import JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from backend.security.qr_security import get_qr_security_manager
from history.models import History

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
                    production = History.objects.get(id=production_id, published=True)
                    response_data["production"] = {
                        "id": str(production.public_id),
                        "name": production.name,
                        "verified": True,
                        "reputation": production.reputation,
                    }
                except History.DoesNotExist:
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


@api_view(["GET"])
@permission_classes([AllowAny])
def qr_security_info(request):
    """
    Get information about QR code security features

    GET /api/security/qr-info/
    """
    return Response(
        {
            "security_features": {
                "hmac_signing": True,
                "expiration_control": True,
                "tamper_detection": True,
                "time_validation": True,
            },
            "supported_versions": ["1.0"],
            "default_expiry_hours": 24 * 365,  # 1 year
            "algorithm": "HMAC-SHA256",
        }
    )


@method_decorator(csrf_exempt, name="dispatch")
class QRSecurityHealthCheck(View):
    """
    Health check endpoint for QR security system
    """

    def get(self, request):
        """GET /api/security/health/"""
        qr_manager = get_qr_security_manager()

        # Get basic health info
        health = {
            "status": "healthy",
            "timestamp": timezone.now().isoformat(),
            "qr_security": {
                "hmac_available": bool(qr_manager.secret_key),
                "signing_key_source": (
                    "secure_storage" if qr_manager._get_signing_key() != qr_manager.secret_key else "fallback"
                ),
            },
        }

        # Add security key manager health if available
        try:
            from backend.security import get_secure_key_manager

            key_manager = get_secure_key_manager()
            key_health = key_manager.health_check()
            health.update(key_health)
        except Exception as e:
            health["status"] = "degraded"
            health["key_manager_error"] = str(e)

        status_code = 200
        if health["status"] == "unhealthy":
            status_code = 503
        elif health["status"] == "degraded":
            status_code = 207

        return JsonResponse(health, status=status_code)


@api_view(["POST"])
@permission_classes([AllowAny])
def validate_production_access(request):
    """
    Validate that a production can be accessed via QR code

    POST /api/security/validate-production/
    {
        "production_id": 123,
        "qr_url": "https://consumer.trazo.io/production/123?p=...&s=..."
    }
    """
    try:
        data = json.loads(request.body)
        production_id = data.get("production_id")
        qr_url = data.get("qr_url")

        if not production_id or not qr_url:
            return Response({"error": "production_id and qr_url are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Verify the QR code
        is_valid, payload, error_message = get_qr_security_manager().verify_qr_url(qr_url)

        if not is_valid:
            return Response({"valid": False, "error": error_message, "security_issue": True}, status=status.HTTP_200_OK)

        # Check if the production ID matches
        qr_production_id = payload.get("id") if payload else None
        if qr_production_id != production_id:
            return Response(
                {"valid": False, "error": "Production ID mismatch", "security_issue": True}, status=status.HTTP_200_OK
            )

        # Check if production exists and is published
        try:
            production = History.objects.get(id=production_id, published=True)
            return Response(
                {
                    "valid": True,
                    "production": {
                        "id": production.id,
                        "name": production.name,
                        "reputation": production.reputation,
                        "start_date": production.start_date,
                        "published": production.published,
                    },
                },
                status=status.HTTP_200_OK,
            )
        except History.DoesNotExist:
            return Response(
                {"valid": False, "error": "Production not found or not published"}, status=status.HTTP_200_OK
            )

    except json.JSONDecodeError:
        return Response({"error": "Invalid JSON"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Production validation error: {e}")
        return Response({"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([AllowAny])
def security_metrics(request):
    """
    Get security metrics for monitoring

    GET /api/security/metrics/
    """
    try:
        # Get basic security metrics
        total_productions = History.objects.filter(published=True).count()

        # Count secure vs legacy QR codes (this would need to be tracked in the database)
        secure_qr_count = 0  # This would need to be implemented with a database field

        return Response(
            {
                "total_productions": total_productions,
                "secure_qr_codes": secure_qr_count,
                "legacy_qr_codes": total_productions - secure_qr_count,
                "security_coverage": (secure_qr_count / total_productions * 100) if total_productions > 0 else 0,
            }
        )
    except Exception as e:
        logger.error(f"Security metrics error: {e}")
        return Response({"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
