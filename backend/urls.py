"""backend URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.urls import include, path
from django.views.decorators.csrf import ensure_csrf_cookie

from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView


@ensure_csrf_cookie
def get_csrf_token(request):
    """
    Global CSRF token endpoint.

    This endpoint ensures the CSRF cookie is set and returns the token
    for use in AJAX requests across the entire application.
    """
    return JsonResponse({"csrf_token": get_token(request), "message": "CSRF token set successfully"})


def simple_test(request):
    """Simple test endpoint that doesn't require database"""
    return JsonResponse({"status": "ok", "message": "Django is working"})


urlpatterns = [
    path("admin/", admin.site.urls),
    # ⛔ `path("accounts/", include("allauth.urls"))` REMOVED 2026-09-07.
    #
    # It mounted 32 public endpoints — login, signup, password reset, email management and
    # social login/callback for Google, Facebook and Apple — and NOTHING used any of them.
    # Verified before removing: no application module imports allauth, the frontend never
    # calls /accounts/, and nothing reverses an allauth URL name. Social sign-in is entirely
    # custom (users/social_auth.py verifies Google ID tokens with PyJWKClient and issues our
    # own simplejwt pair, routed at /api/users/auth/social/).
    #
    # MEASURED against production on 2026-09-07, before this change:
    #     /accounts/password/reset/  ->  200   a working reset form nobody uses
    #     /accounts/signup/          ->  500
    #     /accounts/login/           ->  500
    #
    # The 200 is the problem. It is a SECOND password-reset flow, running allauth's own
    # adapter and templates, sitting beside the reviewed one in users/views.py
    # (request_password_reset). It sends mail from an endpoint nobody monitors, and it
    # bypasses the deliberate anti-enumeration behaviour that resend_verification_email was
    # hardened to (one generic 200 for every address). Two reset paths with different
    # security properties is one too many.
    #
    # These were also invisible to `history.tests.test_anonymous_endpoint_inventory`, which
    # excludes allauth from its sweep as "not our claim surface" — true for claims, not for
    # attack surface.
    #
    # The allauth APPS stay installed: SocialApp and its migrations remain, and
    # users/tests/test_authentication.py patches that model. Only the public URLs go.
    # Removing the dependency outright is a separate piece of work.
    # Global CSRF token endpoint
    path("api/csrf-token/", get_csrf_token, name="csrf_token"),
    # OpenAPI 3.1 schema (source of truth for frontend TypeScript types)
    # Generate types: cd trazo-app && npm run typegen
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/", include("users.urls")),
    path("api/", include("company.urls")),
    path("api/", include("product.urls")),
    path("api/", include("history.urls")),
    path("api/", include("history.urls_consumer")),  # Consumer API endpoints
    path("api/", include("certifications.urls")),  # NOP input verifier (Sprint 3)
    path("api/", include("reviews.urls")),
    path("api/", include("common.urls")),
    path("api/", include("subscriptions.urls")),
    path("api/", include("fieldnotes.urls")),
    path("api/carbon/", include("carbon.urls")),
    path("api/support/", include("support.urls")),
    path("api/education/", include("education.urls")),
    path("api/notifications/", include("notifications.urls")),
    path("api/security/", include("backend.security.urls")),
    # Health check endpoints for container orchestration
    path("", include("health.urls")),
    path("test/", simple_test, name="simple_test"),  # Simple test endpoint
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_URL)
