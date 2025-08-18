"""
Health check views for container orchestration and monitoring
"""

import json
import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["GET"])
def health_check(request):
    """
    Comprehensive health check for container orchestration
    Returns 200 if all systems are healthy, 503 if any system is down
    """
    start_time = time.time()
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "version": getattr(settings, "APP_VERSION", "unknown"),
        "environment": getattr(settings, "ENVIRONMENT", "unknown"),
        "checks": {},
    }

    is_healthy = True

    # Database connectivity check
    try:
        db_conn = connections["default"]
        with db_conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        health_status["checks"]["database"] = {"status": "healthy"}
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        health_status["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
        is_healthy = False

    # Cache connectivity check (if Redis is configured)
    try:
        cache.set("health_check", "ok", 10)
        cache_result = cache.get("health_check")
        if cache_result == "ok":
            health_status["checks"]["cache"] = {"status": "healthy"}
        else:
            raise Exception("Cache set/get mismatch")
    except Exception as e:
        logger.warning(f"Cache health check failed: {str(e)}")
        health_status["checks"]["cache"] = {"status": "unhealthy", "error": str(e)}
        # Cache failures are warnings, not critical

    # Response time check
    response_time = (time.time() - start_time) * 1000  # Convert to ms
    health_status["response_time_ms"] = round(response_time, 2)

    # Set overall status
    if not is_healthy:
        health_status["status"] = "unhealthy"

    # Return appropriate HTTP status
    status_code = 200 if is_healthy else 503

    return JsonResponse(health_status, status=status_code)


@csrf_exempt
@require_http_methods(["GET"])
def readiness_check(request):
    """
    Kubernetes-style readiness check
    Returns 200 when the application is ready to serve traffic
    """
    try:
        # Check if Django can handle requests
        from django.conf import settings

        # Basic readiness indicators
        readiness_status = {
            "status": "ready",
            "timestamp": time.time(),
            "checks": {"django": {"status": "ready"}, "settings": {"status": "loaded"}},
        }

        return JsonResponse(readiness_status, status=200)

    except Exception as e:
        logger.error(f"Readiness check failed: {str(e)}")
        return JsonResponse({"status": "not_ready", "error": str(e), "timestamp": time.time()}, status=503)


@csrf_exempt
@require_http_methods(["GET"])
def liveness_check(request):
    """
    Kubernetes-style liveness check
    Returns 200 if the application process is alive
    """
    return JsonResponse({"status": "alive", "timestamp": time.time()}, status=200)
