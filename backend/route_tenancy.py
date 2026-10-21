"""Who may reach whose rows, declared for every route Trazo serves.

WHY THIS EXISTS
---------------
The permission classes in `backend/permissions.py` return True whenever `view.company is None`,
which is every flat route. On those routes the only thing between one company and another's rows is
the view's own queryset. On 2026-09-28 `/api/companies/` handed every signed-in account every
company and its join code, and probing the routers by hand found seven more routes like it
(`company/tests/test_cross_tenant_routes.py`). Probing by hand finds the routes someone thought of.

This registry is step 1 and 2 of pilot gap #5, the tenancy sweep: an inventory of every route with
its intended scope, and a guard (`backend/tests/test_route_tenancy_declared.py`) that fails CI on a
route nobody declared. It is the worklist for what follows, not the fix.

HOW TO READ AN ENTRY
--------------------
`scope` is what the route is MEANT to allow a signed-in caller to reach. It is a claim about intent.
`outsider_tests` is the evidence: tests in which an account from an unrelated company is refused.
A viewset with one tested action is listed as tested, so treat this as a floor, not coverage.
`finding` is a leak read in the code during the 2026-10-20 inventory and NOT yet reproduced by a
test. Each one is a step-3/4 item. NEVER delete a finding without an outsider test that proves it
closed; replace it with the test name instead.

NEVER: an entry here does not make a route safe. A route with scope COMPANY and no outsider test is
an unchecked claim, and `UNPROVEN_CEILING` counts them so the number can only fall.
"""

from typing import NamedTuple, Optional

COMPANY = "COMPANY"  # rows owned by a company; the caller must work in that company
USER = "USER"  # rows owned by the calling user only
CATALOG = "CATALOG"  # reference data identical for every caller; non-staff may not write
ANONYMOUS = "ANONYMOUS"  # reachable without a session; reviewed in test_anonymous_endpoint_inventory
STAFF = "STAFF"  # staff or superuser only
DEAD = "DEAD"  # no frontend caller, feature retired or never shipped; still reachable, still surface

SCOPES = {COMPANY, USER, CATALOG, ANONYMOUS, STAFF, DEAD}


class Route(NamedTuple):
    scope: str
    why: str
    outsider_tests: tuple = ()
    finding: Optional[str] = None


_CROSS = "company.tests.test_cross_tenant_routes.CrossTenantRouteTests"
_CO = "company.tests.test_company_tenant_isolation"
_REVIEWS = "reviews.tests.test_reviews_scoped.ReviewsScopedTests"

# The shape of most carbon findings: `Establishment.objects.get(id=<request param>)` with no check
# that the caller works in that establishment's company.
_ANY_ESTABLISHMENT = "takes any establishment_id with no membership check"

ROUTE_TENANCY = {
    # ---------------------------------------------------------------------------------------------
    # carbon
    # ---------------------------------------------------------------------------------------------
    "carbon.views.AutomationRuleViewSet": Route(
        DEAD,
        "IoT automation rules; no frontend caller",
        finding=f"list/create/pending_events {_ANY_ESTABLISHMENT}; pending_events with auto_process "
        "WRITES CarbonEntry rows on that farm; approve/reject act on any IoTDataPoint id",
    ),
    "carbon.views.CarbonAuditLogViewSet": Route(USER, "filter(user=request.user)"),
    "carbon.views.CarbonCertificationViewSet": Route(
        COMPANY, "queryset scoped to the caller's companies; _check_owner on create/update"
    ),
    "carbon.views.CarbonEntryViewSet": Route(
        COMPANY,
        "get_queryset scoped to the caller's companies",
        outsider_tests=(f"{_CROSS}.test_carbon_entries_scoped",),
        finding="by_entity and summary bypass get_queryset and filter on any establishment id; "
        "CarbonEntrySerializer resolves establishment_id/production_id with a bare .get(), so "
        "create, bulk_create and update can plant entries on another company's farm",
    ),
    "carbon.views.CarbonEstablishmentSummaryViewSet": Route(
        COMPANY, "403 unless the establishment's company is one of the caller's (is_staff bypasses)"
    ),
    "carbon.views.CarbonFootprintCalculatorViewSet": Route(
        DEAD, "pure calculation, no tenant rows; no frontend caller"
    ),
    "carbon.views.CarbonOffsetActionViewSet": Route(CATALOG, "read-only list of offset action types"),
    "carbon.views.CarbonProductionSummaryViewSet": Route(DEAD, "stub returning a constant"),
    "carbon.views.CarbonProductionViewSet": Route(COMPANY, "filter(parcel__establishment__company__in=user.companies)"),
    "carbon.views.CarbonSourceViewSet": Route(
        CATALOG,
        "global emission sources every entry references",
        finding="ReadOnlyForViewersGlobal lets a CA/FM of ANY company create, edit or delete global "
        "sources, which changes every tenant's figures",
    ),
    "carbon.views.CropTypeViewSet": Route(CATALOG, "read-only, is_active crop types"),
    "carbon.views.EventTemplateViewSet": Route(CATALOG, "read-only templates; use_template bumps a global counter"),
    "carbon.views.IoTDeviceViewSet": Route(
        DEAD,
        "IoT devices; no frontend caller",
        finding=f"list {_ANY_ESTABLISHMENT} and returns device lat/lng; retrieve/update/destroy use a "
        "bare IoTDevice.objects.get(id=pk); simulate_data writes onto any farm",
    ),
    "carbon.views.PublicProductionViewSet": Route(
        COMPANY, "owner-only despite the name: complete_summary filters on the caller's companies"
    ),
    "carbon.views.bulk_verify_entries": Route(USER, "filter(id__in=..., created_by=request.user)"),
    "carbon.views.calculate_event_carbon_impact": Route(CATALOG, "pure calculation from the request body"),
    "carbon.views.calculate_event_carbon_impact_enhanced": Route(CATALOG, "pure calculation from the request body"),
    "carbon.views.calculate_event_impact": Route(
        DEAD,
        "no frontend caller",
        finding="get_object_or_404 on any event id returns another company's event date and carbon",
    ),
    "carbon.views.deepgram_token": Route(COMPANY, "quota read from request.user.get_active_company()"),
    "carbon.views.get_ai_event_suggestions": Route(CATALOG, "query params only, no tenant rows"),
    "carbon.views.get_carbon_impact_examples": Route(CATALOG, "static content"),
    "carbon.views.get_company_crop_options": Route(CATALOG, "static list despite the name"),
    "carbon.views.get_crop_template_detail": Route(CATALOG, "active ProductionTemplate rows"),
    "carbon.views.get_crop_templates": Route(CATALOG, "active ProductionTemplate rows"),
    "carbon.views.get_education_content": Route(CATALOG, "static content"),
    "carbon.views.get_evidence_photos_enhanced": Route(
        COMPANY,
        "creator, or a member of the entry's company",
        finding="the member check reads Company.users, which does not exist: co-members get a 500 "
        "and a stranger gets 404 vs 500, an existence oracle",
    ),
    "carbon.views.get_methodology_templates": Route(CATALOG, "methodology registry only"),
    "carbon.views.get_production_carbon_economics": Route(
        COMPANY, "404 unless the production is in a caller's company"
    ),
    "carbon.views.get_regional_benchmark": Route(
        COMPANY, "per-establishment benchmark", finding=f"path {_ANY_ESTABLISHMENT}; returns its name, state, location"
    ),
    "carbon.views.get_regional_emission_factors": Route(CATALOG, "query params only"),
    "carbon.views.get_regional_farming_practices": Route(CATALOG, "static content"),
    "carbon.views.get_trust_comparison_data": Route(CATALOG, "static content"),
    "carbon.views.get_usda_benchmark_comparison": Route(CATALOG, "query params only"),
    "carbon.views.get_usda_compliance_history": Route(
        DEAD,
        "no frontend caller; the ownership check reads attributes that do not exist, so every call 500s",
        finding="History.objects.get runs before the broken check: 404 vs 500 existence oracle",
    ),
    "carbon.views.get_usda_credibility_info": Route(
        COMPANY,
        "per-establishment factor usage",
        finding=f"path {_ANY_ESTABLISHMENT}; returns its name, city/state and factor usage",
    ),
    "carbon.views.get_usda_methodology_content": Route(CATALOG, "static content"),
    "carbon.views.get_verification_status": Route(USER, "CarbonEntry.objects.get(id=..., created_by=request.user)"),
    "carbon.views.john_deere_auth_callback": Route(DEAD, "John Deere integration never shipped; session state check"),
    "carbon.views.john_deere_auth_start": Route(DEAD, "John Deere integration never shipped"),
    "carbon.views.john_deere_sync_devices": Route(
        DEAD,
        "John Deere integration never shipped",
        finding=f"{_ANY_ESTABLISHMENT}, then get_or_create IoTDevice on it; reach depends on whether "
        "prod holds working John Deere credentials (unconfirmed)",
    ),
    "carbon.views.john_deere_webhook": Route(
        DEAD,
        "John Deere integration never shipped; a webhook with NO signature check, only IsAuthenticated",
        finding=f"any signed-in user POSTs {{establishment_id, fuel_liters}}: {_ANY_ESTABLISHMENT} and "
        "WRITES emission entries onto that farm",
    ),
    "carbon.views.process_voice_event_ai": Route(
        COMPANY, "active company; field note filtered company__in=request.user.companies"
    ),
    "carbon.views.smart_product_search": Route(CATALOG, "product validator only"),
    "carbon.views.smart_product_stats": Route(CATALOG, "product validator only"),
    "carbon.views.smart_product_suggestions_by_type": Route(CATALOG, "product validator only"),
    "carbon.views.smart_product_validation": Route(CATALOG, "product validator only"),
    "carbon.views.upload_evidence_photo_enhanced": Route(
        COMPANY,
        "creator, or a member of the entry's company",
        finding="same nonexistent Company.users check as get_evidence_photos_enhanced; fails closed by accident",
    ),
    "carbon.views.validate_photo_evidence": Route(
        DEAD,
        "no frontend caller; calls a method that does not exist, so it 500s",
        finding="get_object_or_404 on any CarbonEntry id first: 404 vs 500 existence oracle",
    ),
    "carbon.views.validate_usda_compliance": Route(CATALOG, "query params only"),
    "carbon.views.verify_registry_credentials": Route(USER, "CarbonEntry.objects.get(id=..., created_by=request.user)"),
    "carbon.views.voice_config": Route(COMPANY, "request.user.get_active_company()"),
    "carbon.views.weather_alerts": Route(
        COMPANY, "farm weather", finding=f"{_ANY_ESTABLISHMENT}; echoes the farm's exact lat/lng"
    ),
    "carbon.views.weather_create_alert_event": Route(
        DEAD,
        "IoT weather station flow; no frontend caller",
        finding=f"{_ANY_ESTABLISHMENT}; WRITES an IoTDevice and IoTDataPoint onto that farm",
    ),
    "carbon.views.weather_current_conditions": Route(
        COMPANY, "farm weather", finding=f"{_ANY_ESTABLISHMENT}; echoes the farm's exact lat/lng"
    ),
    "carbon.views.weather_forecast": Route(
        COMPANY, "farm weather", finding=f"{_ANY_ESTABLISHMENT}; echoes the farm's exact lat/lng"
    ),
    "carbon.views.weather_recommendations": Route(
        COMPANY, "farm weather", finding=f"{_ANY_ESTABLISHMENT}; echoes the farm's exact lat/lng"
    ),
    "carbon.views.weather_station_webhook": Route(
        DEAD,
        "weather station webhook with no signature check, only IsAuthenticated",
        finding="Establishment.objects.get on any id: existence oracle; writes only an audit row",
    ),
    "carbon.views_security_enhanced.create_secure_carbon_offset": Route(
        COMPANY, "establishment branch checks the caller's companies; production branch raises (500)"
    ),
    "carbon.views_security_enhanced.get_user_security_status": Route(USER, "CarbonAuditLog filtered by user"),
    "carbon.views_security_enhanced.validate_file_upload_security": Route(CATALOG, "pure validation, no tenant rows"),
    # ---------------------------------------------------------------------------------------------
    # certifications, documents. Nested under companies/<company_pk>/establishments/<establishment_pk>/:
    # CompanyNestedViewSet.initial checks membership of company_pk and resolves establishment_pk
    # through self.company.establishment_set, so a foreign establishment 404s.
    # ---------------------------------------------------------------------------------------------
    "certifications.views.AdjoiningLandAffidavitViewSet": Route(
        COMPANY, "nested; queryset and parcel FK scoped to the URL's establishment"
    ),
    "certifications.views.CertificationViewSet": Route(COMPANY, "nested; create forces the URL's establishment"),
    "certifications.views.CertifierAccessLinkViewSet": Route(
        COMPANY,
        "nested; queryset is the URL's establishment",
        finding="within one company: a VIEWER can list live review-link tokens",
    ),
    "certifications.views.LandownerAffidavitViewSet": Route(
        COMPANY,
        "nested; queryset and parcel FK scoped",
        finding="the osp FK is writable against OrganicSystemPlan.objects.all(): links another "
        "company's OSP and confirms the id exists",
    ),
    "certifications.views.OSPAnnualUpdateViewSet": Route(COMPANY, "nested; prior_osp FK scoped to the establishment"),
    "certifications.views.OrganicSystemPlanViewSet": Route(
        COMPANY,
        "nested; all actions go through get_object",
        finding="the certification FK is writable against Certification.objects.all(): links "
        "another company's certificate and confirms the id exists",
    ),
    "certifications.views.PostHarvestFacilityViewSet": Route(COMPANY, "nested; establishment read-only"),
    "certifications.views.StateOrganicRegistrationViewSet": Route(
        COMPANY, "nested; establishment FK pinned to the URL"
    ),
    "certifications.views.buyer_review_metadata": Route(ANONYMOUS, "review-link token, buyer audience"),
    "certifications.views.certifier_review_document_file": Route(ANONYMOUS, "review-link token"),
    "certifications.views.certifier_review_documents": Route(ANONYMOUS, "review-link token"),
    "certifications.views.certifier_review_dossier": Route(ANONYMOUS, "review-link token"),
    "certifications.views.certifier_review_dossier_status": Route(ANONYMOUS, "review-link token"),
    "certifications.views.certifier_review_metadata": Route(ANONYMOUS, "review-link token"),
    "certifications.views.certifier_review_readiness": Route(ANONYMOUS, "review-link token"),
    "certifications.views.certifying_agents": Route(CATALOG, "USDA certifier register snapshot"),
    "certifications.views.verify_input": Route(CATALOG, "National List and OMRI catalog lookups"),
    "documents.views.GeneratedDocumentViewSet": Route(
        COMPANY, "nested; upload links resolved inside the URL's establishment; download via get_object"
    ),
    # ---------------------------------------------------------------------------------------------
    # company, product, reviews
    # ---------------------------------------------------------------------------------------------
    "company.views.CompanyViewSet": Route(
        COMPANY,
        "initial() sets self.company from pk; queryset company_workers__user=request.user",
        outsider_tests=(
            f"{_CO}.CompanyTenantIsolationTests.test_outsider_cannot_retrieve_another_company",
            f"{_CO}.CompanyTenantIsolationTests.test_outsider_cannot_edit_another_company",
        ),
    ),
    "company.views.EstablishmentViewSet": Route(
        COMPANY,
        "CRUD queryset filter(company=self.company); the URL kwarg is pk, not establishment_pk, so "
        "CompanyNestedViewSet's establishment check never runs",
        outsider_tests=(f"{_CROSS}.test_foreign_establishment_under_own_company_url",),
        finding="products, histories, get_charts_data, products_reputation, last_reviews, "
        "rating_reviews_percentage and dashboard_comprehensive use get_object_or_404(Establishment, "
        "pk=pk): a member of A reads B's full dashboard (unpublished seasons) through A's URL; "
        "UpdateEstablishmentSerializer.company is writable, so PATCH moves a farm into another company",
    ),
    "product.views.ParcelCropHistoryViewSet": Route(
        COMPANY,
        "queryset scoped to the caller's companies",
        finding="the parcel FK is writable and unscoped: plants false 205.202 land history on "
        "another company's parcel, which prints in its audit export and OSP",
    ),
    "product.views.ParcelViewSet": Route(
        COMPANY,
        "queryset scoped to the caller's companies",
        outsider_tests=(f"{_CROSS}.test_parcel_read_edit_delete",),
        finding="CreateParcelSerializer.establishment is writable on update: PATCH moves a parcel "
        "and its seasons onto another company's farm (the creation gate checks POST only)",
    ),
    "product.views.ProductsViewSet": Route(CATALOG, "Product has no tenant FK; list only"),
    "reviews.views.ReviewsViewSet": Route(
        COMPANY,
        "list/retrieve need a session and show the caller's own reviews plus reviews of their "
        "companies' seasons; create is anonymous by design (the QR page) but the author is the "
        "session, the season must be published and a scan must be of that season; update/delete "
        "only by the author; establishment_reviews_paginated checks membership of company_id. "
        "get_permissions makes the anonymous create invisible to test_anonymous_endpoint_inventory",
        outsider_tests=(
            f"{_CROSS}.test_review_edit_and_delete_only_by_author",
            f"{_REVIEWS}.test_anonymous_cannot_list_or_retrieve_reviews",
            f"{_REVIEWS}.test_outsider_sees_no_other_tenants_reviews",
            f"{_REVIEWS}.test_paginated_list_refuses_a_company_the_caller_does_not_work_in",
            f"{_REVIEWS}.test_review_cannot_be_posted_as_another_user",
            f"{_REVIEWS}.test_unpublished_season_cannot_be_reviewed",
            f"{_REVIEWS}.test_scan_must_belong_to_the_reviewed_season",
        ),
    ),
    # ---------------------------------------------------------------------------------------------
    # history, fieldnotes
    # ---------------------------------------------------------------------------------------------
    "history.claim_preview_views.input_status_preview": Route(CATALOG, "stateless dry-run over input catalogs"),
    "history.transparency_views.production_transparency_detail": Route(ANONYMOUS, "the QR product page"),
    "history.transparency_views.verify_blockchain": Route(ANONYMOUS, "published productions only"),
    "history.views.BuyerDocRequestViewSet": Route(
        COMPANY, "create needs a published season; list/patch need CA/FM on the establishment"
    ),
    "history.views.EventViewSet": Route(
        COMPANY,
        "_scope_to_caller on get_queryset and get_object; create parcels scoped to the caller",
        finding="within one company: on the flat route a VIEWER can create, edit and delete events",
    ),
    "history.views.HistoryScanViewSet": Route(
        COMPANY,
        "scope_to_caller_companies",
        outsider_tests=(f"{_CROSS}.test_scan_read_and_delete",),
        finding="within one company: on the flat route a VIEWER can edit and delete scans",
    ),
    "history.views.HistoryViewSet": Route(
        COMPANY,
        "scope_to_caller_companies; writes check CA/FM; public_history is AllowAny and reviewed",
        outsider_tests=(f"{_CROSS}.test_season_retrieve_by_id_and_uuid", f"{_CROSS}.test_season_list_shows_only_own"),
        finding="establishment_scans_paginated overrides permissions to IsAuthenticated and filters on "
        "query-param ids: any account reads any farm's scans with scanner names and IP addresses; "
        "my_reviews returns the owner HistorySerializer for any season the caller reviewed (reviews "
        "create accepts any production id); download_qr_code by UUID is unscoped",
    ),
    "history.views.PublicHistoryScanViewSet": Route(
        ANONYMOUS,
        "shopper scans; create needs a published season, consent and claim need the claim token",
        finding="inherited destroy runs on HistoryScan.objects.all() with AllowAny: anonymous DELETE "
        "/api/public_scans/<int>/ removes any farm's scan; comment writes onto any farm's scan by id",
    ),
    "history.views.RecordsExportViewSet": Route(COMPANY, "nested only; any member role may export"),
    "history.views.SalesRecordViewSet": Route(COMPANY, "CA/FM on the production; foreign harvest events rejected"),
    "history.views.audit_export_by_uuid": Route(COMPANY, "WorksIn on the production's company (any role)"),
    "history.views_consumer.ConsumerDashboardViewSet": Route(
        USER,
        "impact and shopping filtered on the user",
        finding="compare_products filters public_id__in with no published check: an unpublished "
        "season's farm name, location, carbon and certifications to any UUID holder",
    ),
    "history.views_consumer.UserFavoriteViewSet": Route(
        USER,
        "list filtered on the user",
        finding="toggle_favorite takes any integer production id, published or not; the favorites "
        "list then returns its public UUID, farm name, location and carbon (turns ids into UUIDs)",
    ),
    "history.views_consumer.UserShoppingGoalViewSet": Route(USER, "filter(user=request.user)"),
    "fieldnotes.views.CrewSenderViewSet": Route(
        COMPANY, "company__in=user.companies; writes need CA/FM in the row's company"
    ),
    "fieldnotes.views.FieldNoteViewSet": Route(
        COMPANY,
        "company__in=user.companies",
        finding="within one company: a VIEWER who is CA/FM elsewhere can discard or acknowledge notes",
    ),
    "fieldnotes.views.inbound_message_webhook": Route(ANONYMOUS, "Twilio HMAC signature, fails closed"),
    # ---------------------------------------------------------------------------------------------
    # common, education
    # ---------------------------------------------------------------------------------------------
    "common.views.get_presigned_read_url": Route(CATALOG, "signs public-prefix media keys only"),
    "common.views.get_presigned_read_urls_batch": Route(CATALOG, "signs public-prefix media keys only"),
    "common.views.get_presigned_url": Route(USER, "uuid key under media/; no overwrite"),
    "common.views.get_upload_urls": Route(
        COMPANY,
        "uuid key, no overwrite",
        finding="entity_type/entity_id go into the key unchecked: objects can be planted under "
        "another company's prefix; whether any reader trusts the prefix is unconfirmed",
    ),
    "common.views.global_search": Route(COMPANY, "company_id__in the caller's companies"),
    "common.views.health_check": Route(ANONYMOUS, "liveness probe"),
    "common.views.local_file_upload": Route(DEAD, "dev-only upload still routed in production"),
    "education.views.FarmerQuestionAnswerViewSet": Route(CATALOG, "FAQ rows; mark_helpful bumps a global counter"),
    # ---------------------------------------------------------------------------------------------
    # users
    # ---------------------------------------------------------------------------------------------
    "users.views.UserViewSet": Route(
        USER,
        "non-superusers get filter(id=request.user.id); verify/reset actions are AllowAny",
        finding="email changes without re-verification (the is_superuser self-escalation is fixed in "
        "#188, guard users.tests.test_user_privilege_fields_read_only)",
    ),
    "users.views.LoginViewSet": Route(ANONYMOUS, "sign-in"),
    "users.views.RegistrationViewSet": Route(ANONYMOUS, "sign-up"),
    "users.views.CustomTokenRefreshView": Route(ANONYMOUS, "refresh cookie"),
    "users.views.APILogoutView": Route(USER, "blacklists the caller's own refresh cookie"),
    "users.social_auth.SocialAuthView": Route(
        ANONYMOUS,
        "Google ID token checked for audience and issuer",
        finding="the access-token fallback calls Google userinfo with no audience check, and Facebook "
        "has no debug_token app check: a token issued to ANOTHER app signs in as the victim",
    ),
    "users.social_auth.OAuthConfigView": Route(ANONYMOUS, "public client ids"),
    "users.views_invitation.accept_invitation": Route(ANONYMOUS, "invitation code; email match when signed in"),
    "users.views_invitation.cancel_invitation": Route(COMPANY, "inviter or CA of the invitation's company"),
    "users.views_invitation.create_invitation": Route(COMPANY, "CA of the caller's company"),
    "users.views_invitation.decline_invitation": Route(
        USER,
        "signed in, plus the invitation code",
        finding="no check that the caller is the invitee: any account holding a code can kill it",
    ),
    "users.views_invitation.get_invitation_details": Route(ANONYMOUS, "invitation code, about 82 bits"),
    "users.views_invitation.list_invitations": Route(COMPANY, "filter(company=the caller's CA company)"),
    "users.views_invitation.resend_invitation": Route(COMPANY, "inviter or CA of the invitation's company"),
    "users.views_invitation.signup_with_invitation": Route(ANONYMOUS, "invitation code"),
    # ---------------------------------------------------------------------------------------------
    # subscriptions, support, notifications
    # ---------------------------------------------------------------------------------------------
    "subscriptions.views.PlanViewSet": Route(ANONYMOUS, "public pricing; internal plans excluded"),
    "subscriptions.views.AddOnViewSet": Route(CATALOG, "active add-ons"),
    "subscriptions.views.SubscriptionViewSet": Route(
        COMPANY,
        "filter(company__in=user.companies); writes need CA of obj.company",
        finding="within one company: status and period fields are writable, so a CA can PATCH "
        "status=active; start_trial answers 404 vs 403 on company ids",
    ),
    "subscriptions.views.InvoiceViewSet": Route(COMPANY, "filter(company__in=user.companies)"),
    "subscriptions.views.PaymentMethodViewSet": Route(
        COMPANY,
        "filter(company__in=user.companies)",
        finding="within one company: destroy and set_default have no CA check",
    ),
    "subscriptions.views.CheckoutViewSet": Route(COMPANY, "CA of the company named in the request"),
    "subscriptions.views.stripe_webhook": Route(
        ANONYMOUS,
        "Stripe signature via construct_event",
        finding="STRIPE_WEBHOOK_SECRET defaults to an empty string; confirm it is set in production",
    ),
    "subscriptions.views.BlockchainSubscriptionView": Route(DEAD, "blockchain add-on withdrawn; 404 unless enabled"),
    "subscriptions.views.BlockchainSubscriptionStatusView": Route(
        DEAD, "blockchain add-on withdrawn; a GET with ?sync=1 writes company state"
    ),
    "support.views.SupportTicketViewSet": Route(
        COMPANY,
        "filter(company__in=user.companies); queue/metrics/assign need is_staff",
        finding="assigned_to accepts any user id and echoes assigned_to_name: enumerates every "
        "user's full name; within a ticket a customer can read and write internal_notes",
    ),
    "support.views.SupportMessageViewSet": Route(COMPANY, "ticket__company__in the caller's companies"),
    "support.views.SupportAttachmentViewSet": Route(
        COMPANY,
        "reads scoped to the caller's tickets",
        finding="ticket and message FKs are writable and unchecked: a file can be attached to "
        "another company's ticket",
    ),
    "notifications.views.NotificationListView": Route(USER, "filter(recipient=user)"),
    "notifications.views.NotificationPreferenceView": Route(USER, "get_or_create(user=request.user)"),
    "notifications.views.NotificationChannelListView": Route(USER, "filter(user=request.user)"),
    "notifications.views.NotificationTemplateListCreateView": Route(STAFF, "IsAdminUser"),
    "notifications.views.NotificationTemplateDetailView": Route(STAFF, "IsAdminUser"),
    "notifications.views.create_notification": Route(STAFF, "IsAdminUser"),
    "notifications.views.delete_notification": Route(USER, "get(id=..., recipient=request.user)"),
    "notifications.views.mark_all_as_read": Route(USER, "filter(recipient=request.user)"),
    "notifications.views.mark_notification_as_read": Route(USER, "get(id=..., recipient=user)"),
    "notifications.views.notification_count": Route(USER, "filter(recipient=user)"),
    "notifications.views.notification_stats": Route(USER, "filter(recipient=user)"),
    "notifications.views.test_notification": Route(USER, "recipient is the caller"),
    # ---------------------------------------------------------------------------------------------
    # platform: security utilities, health, schema, router root
    # ---------------------------------------------------------------------------------------------
    "backend.security.views.QRSecurityHealthCheck": Route(
        ANONYMOUS,
        "security health probe",
        finding="calls Secrets Manager per request and returns str(e) to anonymous callers; check "
        "whether the error text carries the IAM ARN or account id",
    ),
    "backend.security.views.qr_security_info": Route(ANONYMOUS, "static QR format help"),
    "backend.security.views.security_metrics": Route(ANONYMOUS, "aggregate counters"),
    "backend.security.views.validate_production_access": Route(ANONYMOUS, "published productions only"),
    "backend.security.views.verify_qr_code": Route(ANONYMOUS, "HMAC-checked, published productions only"),
    "backend.urls.get_csrf_token": Route(ANONYMOUS, "issues the CSRF cookie"),
    "backend.urls.simple_test": Route(DEAD, "static ok at /test/, not gated by DEBUG"),
    "health.views.health_check": Route(ANONYMOUS, "probe; returns exception text on failure"),
    "health.views.liveness_check": Route(ANONYMOUS, "probe"),
    "health.views.readiness_check": Route(ANONYMOUS, "probe; returns exception text on failure"),
    "drf_spectacular.views.SpectacularAPIView": Route(ANONYMOUS, "OpenAPI schema, reviewed as public"),
    "drf_spectacular.views.SpectacularSwaggerView": Route(ANONYMOUS, "API docs UI"),
    "drf_spectacular.views.SpectacularRedocView": Route(ANONYMOUS, "API docs UI"),
    "rest_framework.routers.APIRootView": Route(CATALOG, "lists router prefixes"),
}

# Company- or user-scoped views with no outsider test. Lower it as tests land; never raise it.
UNPROVEN_CEILING = 68

# Declarations carrying a `finding`, any scope. Same rule: lower it as findings close.
OPEN_FINDINGS_CEILING = 42
