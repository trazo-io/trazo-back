# Certifications app URLs.
#
# CertificationViewSet is registered via company/urls.py establishment_router (nested route).
# Standalone endpoints (like the NOP input verifier) live here.

from django.urls import path

from .views import (
    buyer_review_metadata,
    certifier_review_dossier,
    certifier_review_dossier_status,
    certifier_review_metadata,
    certifier_review_readiness,
    certifying_agents,
    verify_input,
)

urlpatterns = [
    # NOP input verifier (Sprint 3) — classify a chemical/amendment against the
    # National List (7 CFR 205.601/602) and/or a farmer-supplied OMRI ID.
    path("certifications/verify-input/", verify_input, name="verify_input"),
    # The certifier picker's list — agents by Organic Integrity Database spelling, each flagged with
    # whether the packet speaks its form numbers.
    path("certifications/certifying-agents/", certifying_agents, name="certifying_agents"),
    # Certifier review links — ANONYMOUS by design. The certifier needs no Trazo
    # account; the token in the URL is the credential. Both views resolve only
    # ACTIVE links (not expired, not revoked) and log every open.
    path(
        "buyer-review/<str:token>/",
        buyer_review_metadata,
        name="buyer_review_metadata",
    ),
    path(
        "certifier-review/<str:token>/",
        certifier_review_metadata,
        name="certifier_review_metadata",
    ),
    path(
        "certifier-review/<str:token>/readiness/",
        certifier_review_readiness,
        name="certifier_review_readiness",
    ),
    path(
        "certifier-review/<str:token>/dossier/",
        certifier_review_dossier,
        name="certifier_review_dossier",
    ),
    path(
        "certifier-review/<str:token>/dossier/status/",
        certifier_review_dossier_status,
        name="certifier_review_dossier_status",
    ),
]
