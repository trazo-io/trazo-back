# Certifications app URLs.
#
# CertificationViewSet is registered via company/urls.py establishment_router (nested route).
# Standalone endpoints (like the NOP input verifier) live here.

from django.urls import path

from .views import verify_input

urlpatterns = [
    # NOP input verifier (Sprint 3) — classify a chemical/amendment against the
    # National List (7 CFR 205.601/602) and/or a farmer-supplied OMRI ID.
    path("certifications/verify-input/", verify_input, name="verify_input"),
]
