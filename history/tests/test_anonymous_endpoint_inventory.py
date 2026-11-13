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
    # Per action since 2026-11-13: one viewset-wide entry used to cover them all, and
    # `confirm_email_change` was anonymous without appearing in its reason.
    "UserViewSet.verify_email::AllowAny": "email verification token from the sign-up mail",
    "UserViewSet.resend_verification_email::AllowAny": "the user is not signed in until verified",
    "UserViewSet.request_password_reset::AllowAny": "forgotten password; same response for any address",
    "UserViewSet.confirm_password_reset::AllowAny": "reset token from the mail is the credential",
    "UserViewSet.confirm_email_change::AllowAny": (
        "token sent only to the new address is the credential; the link may open signed out (OV-SEC-C03)"
    ),
    "signup_with_invitation::AllowAny": "invited user has no account yet",
    "get_invitation_details::AllowAny": "invitation code lookup before sign-up",
    "accept_invitation::AllowAny": "invitation acceptance before sign-up",
    # --- The consumer QR surface. THE claim-safety surface: every byte is gated by
    #     claim_authority.py and covered by test_cross_surface_claim_safety. ---
    "production_transparency_detail::AllowAny": "the QR product page (UUID-only lookup)",
    # `transparency_explanation` was REMOVED on 2026-08-30. Its entry here read "static
    # methodology copy, no farm data" — true, and the reason it survived. The endpoint
    # published "Understanding Farm Transparency Scores" plus a four-band grading rubric
    # (90-100% excellent / 70-89% good / 50-69% basic / 0-49% limited) and the line "Verify
    # sustainability claims with real data", anonymously, for a score withheld from
    # consumers since 2026-08-11 and unread by any component. A self-created grading scale
    # is the EU ECGT 2024/825 label class whether or not a farm's data is attached, so this
    # inventory reviews CLAIM exposure as well as DATA exposure.
    "verify_blockchain::AllowAny": "integrity check for a published production",
    "HistoryViewSet.public_history::AllowAny": "the season page; anonymous callers need the UUID",
    # `HistoryViewSet.validate_qr` was REMOVED on 2026-11-13: anonymous, looked a published season
    # up by its integer id (or the first number in any string), had no caller, and redirected to a
    # route that does not exist.
    "PublicHistoryScanViewSet::AllowAny": "shopper scan tally; consent gating in PrivacyService",
    "PublicHistoryScanViewSet.upgrade_consent::AllowAny": "claim_token authorises it (256-bit, unique)",
    "PublicHistoryScanViewSet.comment::AllowAny": "authorised by claim_token, as consent is; one comment per scan",
    # --- Certifier review links. Bearer-token in the URL is the credential. ---
    "certifier_review_metadata::AllowAny": "opaque review token",
    "certifier_review_readiness::AllowAny": "opaque review token",
    "certifier_review_dossier::AllowAny": "opaque review token",
    "certifier_review_dossier_status::AllowAny": (
        "opaque review token; build status + progress of the dossier only, no records"
    ),
    "certifier_review_documents::AllowAny": (
        "opaque review token; the list of uploaded source files (title, folder, linked record, "
        "size) only when the grower ticked include_source_files at link creation, else empty"
    ),
    "certifier_review_document_file::AllowAny": (
        "opaque review token; streams ONE uploaded file in the link's scope, only when "
        "include_source_files is set; logged per open; per-link hourly ceiling; 404 after revoke"
    ),
    "certifier_review_traceback_search::AllowAny": (
        "opaque review token, certifier audience only; finds sales of the LINK's farm inside its "
        "window by the number on a document (same matcher as the operation's own page); the result "
        "rows (date, buyer, invoice, crop, parcel, season) are already in the dossier; logged per "
        "request as 'traced a sale'; per-link hourly ceiling; 404 after revoke"
    ),
    "certifier_review_traceback::AllowAny": (
        "opaque review token, certifier audience only; one sale of the link's farm and window "
        "traced to its picks, season and inputs (the dossier's own content class: buyers, "
        "invoices, suppliers, lots); files carry a token-route id only when include_source_files "
        "is set, else title only; internal ids stripped; logged; same 404 as an unknown sale"
    ),
    "certifier_review_lot_traceback_search::AllowAny": (
        "opaque review token, certifier audience only; finds harvest picks of the LINK's farm "
        "inside its window by a lot code, packer's receipt or season lot ID (same matcher as the "
        "operation's own page); the rows (date, lot code, block, quantity, storage, crop, parcel, "
        "season) are already in the dossier; logged per request; per-link hourly ceiling"
    ),
    "certifier_review_lot_traceback::AllowAny": (
        "opaque review token, certifier audience only; one harvest pick of the link's farm and "
        "window traced back to its season and inputs and forward to the sales that name it, plus "
        "recorded harvested minus recorded sold per storage location (the dossier's own content "
        "class); files as on the sale trace; internal ids stripped; logged; same 404 as unknown"
    ),
    "buyer_review_metadata::AllowAny": (
        "opaque review token, buyer audience only. Payload: operation name/city/state (same "
        "exposure as certifier_review_metadata) plus a season LIST (public uuid, crop, parcel "
        "name, dates, published flag) — no events, no PII, no claims; season detail flows "
        "through public_history's claim-safe serializer"
    ),
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
    "fieldnotes.views.inbound_message_webhook::NON-DRF": (
        "WhatsApp inbound messages. Signature-authenticated per provider (Twilio HMAC-SHA1 over the "
        "URL plus sorted params, compared with hmac.compare_digest); 400 on a bad OR MISSING "
        "signature, and an unset TWILIO_AUTH_TOKEN fails CLOSED rather than accepting everything. "
        "Writes only a FieldNote, and only for a number on an ACTIVE, consent-attested per-company "
        "CrewSender roster; an unrostered sender gets 200 and silence, because a refusal message "
        "would confirm to a stranger that the line is live. A number rostered by two companies is "
        "refused rather than routed by heap order. PUBLISHES NOTHING: the response body is always "
        "empty, so there is no PII, no geodata and no claim for a stranger with the URL to read."
    ),
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
    name = view_class.__name__
    if "permission_classes" in initkwargs:
        # An `@action` that sets its own permissions is reviewed BY ACTION. Keyed by the viewset
        # alone, one reviewed public action approved every sibling: `HistoryViewSet.validate_qr`
        # (AllowAny, integer-id lookup, no caller) sat under the entry written for
        # `public_history` until 2026-11-13.
        actions = getattr(callback, "actions", None) or {}
        name = f"{name}.{'/'.join(sorted(set(actions.values())))}"
    return name, [_permission_name(p) for p in permissions]


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
        self.assertIn(
            "HistoryViewSet.public_history::AllowAny",
            found,
            "An @action with its own permissions must be keyed by action, or one reviewed public "
            "action approves every sibling on the viewset.",
        )
