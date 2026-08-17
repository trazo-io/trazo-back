"""
Every anonymously-reachable API endpoint is on an explicit, reviewed list.

WHY THIS EXISTS
---------------
Seven consumer claim/PII leaks have shipped, and each was found the same way: a human went
looking. The claim-safety sweep (`test_cross_surface_claim_safety`) is good at reading the BYTES
of endpoints it already knows about — and structurally blind to an endpoint it has never heard
of. That is the same denylist shape the sweep itself was written to escape, moved up one layer to
routing.

Two of today's findings arrived exactly that way:

  * `carbon/public/productions/<pk>/complete/` — anonymous and integer-pk enumerable for months,
    hand-building its own establishment/company/parcel payload, so every PII and claim fix applied
    to the transparency views had to be rediscovered and reapplied to it. Now owner-only.
  * `companies/public/establishments/<pk>/` — anonymous, `permission_classes = []`, publishing
    street address, ZIP, exact lat/lon, farm email and phone, `farming_method`,
    `sustainability_practices` and the free-text `certifications` string. Zero frontend callers.

This test inverts the burden of proof. A new anonymous endpoint fails CI until someone writes it
down here with a reason. It cannot tell you an endpoint is SAFE — only that nobody has silently
added a public surface without saying so.

WHAT IT DOES NOT COVER
----------------------
Only the permission CLASS is inspected. A view that keeps `AllowAny` and narrows inside
`get_permissions()` (RegistrationViewSet: `create` open, everything else authenticated) is still
listed here — the entry documents the real rule. That direction is the safe one to be wrong in.
"""

from django.test import SimpleTestCase
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

# Anonymous API surface, reviewed 2026-08-12. Key: "<view class or function>::<permissions>".
#
# ⛔ Adding a line here is a DECISION, not a formality. Before you do, confirm the payload is
# claim-safe and PII-free for a stranger with the URL — `claim_authority.py` decides what a public
# surface may assert, and `history/services/privacy.py` decides what geodata it may carry.
REVIEWED_ANONYMOUS_ENDPOINTS = {
    # --- Auth / account lifecycle. Anonymous by necessity: the caller has no session yet. ---
    "LoginViewSet::AllowAny": "sign-in",
    "RegistrationViewSet::AllowAny": "sign-up (get_permissions narrows all other actions)",
    "CustomTokenRefreshView::AllowAny": "refresh from the httpOnly cookie",
    "SocialAuthView::AllowAny": "Google OAuth exchange",
    "OAuthConfigView::AllowAny": "public client id / redirect URI",
    "UserViewSet::AllowAny": "verify_email, request/confirm_password_reset, resend_verification",
    "signup_with_invitation::AllowAny": "invited user has no account yet",
    "get_invitation_details::AllowAny": "invitation code lookup before sign-up",
    "accept_invitation::AllowAny": "invitation acceptance before sign-up",
    # --- The consumer QR surface. THE claim-safety surface: every byte is gated by
    #     claim_authority.py and covered by test_cross_surface_claim_safety. ---
    "production_transparency_detail::AllowAny": "the QR product page (UUID-only lookup)",
    "transparency_explanation::AllowAny": "static methodology copy, no farm data",
    "verify_blockchain::AllowAny": "integrity check for a published production",
    "HistoryViewSet::AllowAny": "public_history action only — the @action carries AllowAny",
    "PublicHistoryScanViewSet::AllowAny": "shopper scan tally; consent gating in PrivacyService",
    # --- Certifier review links. Bearer-token in the URL is the credential. ---
    "certifier_review_metadata::AllowAny": "opaque review token",
    "certifier_review_readiness::AllowAny": "opaque review token",
    "certifier_review_dossier::AllowAny": "opaque review token",
    # --- Pricing + docs. No farm data. ---
    "PlanViewSet::AllowAny": "public pricing table",
    "SpectacularAPIView::AllowAny": "OpenAPI schema",
    "SpectacularSwaggerView::AllowAny": "API docs UI",
    "SpectacularRedocView::AllowAny": "API docs UI",
    # --- Security utilities. Must not echo farm data; see backend/security/views.py. ---
    "qr_security_info::AllowAny": "QR format help, no farm data",
    "verify_qr_code::AllowAny": "QR signature check",
    "validate_production_access::AllowAny": "public-visibility check for a production",
    "security_metrics::AllowAny": "aggregate counters only",
    # --- Plain Django views: no DRF permission layer at all. Module-qualified so a new view
    #     cannot inherit one of these approvals by sharing a decorator wrapper's name. ---
    "backend.urls.get_csrf_token::NON-DRF": "issues the CSRF cookie; must be reachable pre-auth",
    "common.views.health_check::NON-DRF": "liveness probe",
    "backend.security.views.view::NON-DRF": "security health probe (decorator-wrapped)",
    "subscriptions.views.stripe_webhook::NON-DRF": "Stripe calls it; signature-authenticated, not session",
}


def _walk(resolver, prefix=""):
    for pattern in resolver.url_patterns:
        full = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            yield from _walk(pattern, full)
        elif isinstance(pattern, URLPattern):
            yield full, pattern


def _permission_name(permission):
    """DRF composes permissions into `OperandHolder`s (`A | B`), which have no `__name__`."""
    name = getattr(permission, "__name__", None)
    if name:
        return name
    op1 = getattr(permission, "op1_class", None)
    op2 = getattr(permission, "op2_class", None)
    if op1 or op2:
        operator = getattr(permission, "operator_class", None)
        return f"({_permission_name(op1)} {getattr(operator, '__name__', '?')} {_permission_name(op2)})"
    return repr(permission)


def _view_identity(pattern):
    """(view name, permission names) for a route.

    `@action(permission_classes=[...])` routes carry their own permissions in `initkwargs`, which
    is what makes per-action gating visible here — `HistoryViewSet.public_history` is AllowAny
    while the rest of the viewset is not.

    A plain Django view has no DRF permission layer AT ALL, so it is reported as `NON-DRF` and
    must be reviewed like any other anonymous surface. Skipping them (the first version of this
    test did) would have left a hole big enough for the next public endpoint to walk through:
    nothing stops someone adding `path("api/whatever/", a_plain_view)`.
    """
    callback = pattern.callback
    view_class = getattr(callback, "cls", None)
    if view_class is None:
        # Module-qualified on purpose. Decorator wrappers are routinely named `view`, so a bare
        # `__name__` would let a brand-new public view inherit an existing entry's approval.
        name = getattr(callback, "__name__", repr(callback))
        return f"{getattr(callback, '__module__', '?')}.{name}", ["NON-DRF"]
    initkwargs = getattr(callback, "initkwargs", None) or {}
    permissions = initkwargs.get("permission_classes", getattr(view_class, "permission_classes", None))
    if permissions is None:
        return f"{view_class.__module__}.{view_class.__name__}", ["NON-DRF"]
    return view_class.__name__, [_permission_name(p) for p in permissions]


class AnonymousEndpointInventoryTests(SimpleTestCase):
    """No new anonymous API endpoint without an explicit, reviewed entry."""

    def _anonymous_api_endpoints(self):
        found = {}
        for route, pattern in _walk(get_resolver()):
            if not route.startswith("api/"):
                continue  # admin, allauth, static and health probes are not our claim surface
            view_name, permissions = _view_identity(pattern)
            # Anonymous means: AllowAny, an EMPTY permission list (no checks run at all — how
            # `companies/public/establishments/` shipped its PII), or no DRF layer at all.
            anonymous = not permissions or any("AllowAny" in name for name in permissions) or permissions == ["NON-DRF"]
            if not anonymous:
                continue
            key = f"{view_name}::{','.join(permissions) or 'EMPTY'}"
            found.setdefault(key, set()).add(route)
        return found

    def test_no_unreviewed_anonymous_endpoint(self):
        found = self._anonymous_api_endpoints()
        unreviewed = sorted(set(found) - set(REVIEWED_ANONYMOUS_ENDPOINTS))

        detail = "\n".join(f"  {key}\n     routes: {sorted(found[key])}" for key in unreviewed)
        self.assertEqual(
            unreviewed,
            [],
            "Anonymous API endpoint(s) with no reviewed entry.\n\n"
            f"{detail}\n\n"
            "A stranger with the URL can call these. Confirm the payload carries no PII "
            "(street address, coordinates, ZIP, contact details) and no unqualified claim "
            "(certifications, farming_method, sustainability_practices, any self-assigned "
            "grade) — then add it to REVIEWED_ANONYMOUS_ENDPOINTS with the reason. If nothing "
            "calls it, delete it instead: an unused public endpoint is the cheapest leak there "
            "is.",
        )

    def test_reviewed_list_has_no_stale_entries(self):
        """An entry for a route that no longer exists is a lie about the current surface.

        It also silently re-permits the endpoint if it ever comes back.
        """
        found = self._anonymous_api_endpoints()
        stale = sorted(set(REVIEWED_ANONYMOUS_ENDPOINTS) - set(found))
        self.assertEqual(
            stale,
            [],
            f"REVIEWED_ANONYMOUS_ENDPOINTS lists endpoints that no longer exist: {stale}. "
            "Remove them so the list describes the real surface.",
        )

    def test_the_inventory_actually_finds_endpoints(self):
        """Guards the guard: a walker that silently returns nothing would pass both tests."""
        found = self._anonymous_api_endpoints()
        self.assertGreaterEqual(
            len(found),
            15,
            f"Only {len(found)} anonymous endpoints discovered — the URLconf walk is probably "
            "broken, which would make the assertions above vacuous.",
        )
        self.assertIn(
            "production_transparency_detail::AllowAny",
            found,
            "The consumer QR endpoint was not discovered — the walk is not seeing real routes.",
        )
