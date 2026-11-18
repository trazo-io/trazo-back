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
_FLAT = "backend.tests.test_flat_routes_fail_closed.FlatRouteWritesAreRoleCheckedTests"
_FLATX = "backend.tests.test_flat_routes_fail_closed.CrossCompanyObjectTests"
_FK = "company.tests.test_fk_writes_scoped.ForeignKeyWritesScopedTests"
_CARBON = "company.tests.test_fk_writes_scoped.CarbonReadsScopedTests"
_FKR = "company.tests.test_fk_writes_scoped.ReviewFollowUpTests"
_EST = "company.tests.test_establishment_actions_scoped.EstablishmentActionsScopedTests"
_SCANS = "history.tests.test_scans_paginated_scoped.ScansPaginatedScopedTests"
_REVIEWS = "reviews.tests.test_reviews_scoped.ReviewsScopedTests"
_PUBSCANS = "history.tests.test_public_scans_scoped.PublicScansScopedTests"
_SALETRACE = "history.tests.test_sale_traceback"
_LOTTRACE = "history.tests.test_lot_traceback"
_WA_EXPORT = "history.tests.test_wa_spray_record_export.DoorTests"


ROUTE_TENANCY = {
    # ---------------------------------------------------------------------------------------------
    # carbon
    # ---------------------------------------------------------------------------------------------
    "carbon.views.CarbonAuditLogViewSet": Route(USER, "filter(user=request.user)"),
    "carbon.views.CarbonCertificationViewSet": Route(
        COMPANY, "queryset scoped to the caller's companies; _check_owner on create/update"
    ),
    "carbon.views.CarbonEntryViewSet": Route(
        COMPANY,
        "get_queryset scoped to the caller's companies, by_entity and summary included; "
        "establishment/production (and their *_id twins) accept only the caller's rows",
        outsider_tests=(
            f"{_CROSS}.test_carbon_entries_scoped",
            f"{_FK}.test_carbon_entry_cannot_be_planted_on_another_companys_farm",
            f"{_CARBON}.test_by_entity_returns_nothing_for_another_companys_farm",
            f"{_CARBON}.test_summary_returns_nothing_for_another_companys_farm",
        ),
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
    "carbon.views.PublicProductionViewSet": Route(
        COMPANY, "owner-only despite the name: complete_summary filters on the caller's companies"
    ),
    "carbon.views.calculate_event_carbon_impact": Route(CATALOG, "pure calculation from the request body"),
    "carbon.views.calculate_event_carbon_impact_enhanced": Route(CATALOG, "pure calculation from the request body"),
    "carbon.views.deepgram_token": Route(COMPANY, "quota read from request.user.get_active_company()"),
    "carbon.views.get_ai_event_suggestions": Route(CATALOG, "query params only, no tenant rows"),
    "carbon.views.get_company_crop_options": Route(CATALOG, "static list despite the name"),
    "carbon.views.get_crop_template_detail": Route(CATALOG, "active ProductionTemplate rows"),
    "carbon.views.get_crop_templates": Route(CATALOG, "active ProductionTemplate rows"),
    "carbon.views.get_evidence_photos_enhanced": Route(
        COMPANY,
        "creator, or a member of the entry's company",
        finding="the member check reads Company.users, which does not exist: co-members get a 500 "
        "and a stranger gets 404 vs 500, an existence oracle",
    ),
    "carbon.views.get_production_carbon_economics": Route(
        COMPANY, "404 unless the production is in a caller's company"
    ),
    "carbon.views.get_regional_emission_factors": Route(CATALOG, "query params only"),
    "carbon.views.get_usda_benchmark_comparison": Route(CATALOG, "query params only"),
    "carbon.views.get_usda_compliance_history": Route(
        DEAD,
        "no frontend caller; the ownership check reads attributes that do not exist, so every call 500s",
        finding="History.objects.get runs before the broken check: 404 vs 500 existence oracle",
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
    "carbon.views.voice_config": Route(COMPANY, "request.user.get_active_company()"),
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
        "nested; queryset and parcel FK scoped; the osp FK accepts only the caller's OSPs",
        outsider_tests=(
            f"{_FK}.test_affidavit_cannot_attach_to_another_companys_osp",
            f"{_FKR}.test_affidavit_cannot_attach_to_another_farms_osp_in_the_same_company",
        ),
    ),
    "certifications.views.OSPAnnualUpdateViewSet": Route(COMPANY, "nested; prior_osp FK scoped to the establishment"),
    "certifications.views.OrganicSystemPlanViewSet": Route(
        COMPANY,
        "nested; all actions go through get_object; the certification FK accepts only the caller's",
        outsider_tests=(
            f"{_FK}.test_osp_cannot_link_another_companys_certification",
            f"{_FKR}.test_osp_cannot_link_another_farms_certificate_in_the_same_company",
        ),
    ),
    "certifications.views.PostHarvestFacilityViewSet": Route(COMPANY, "nested; establishment read-only"),
    "certifications.views.FacilityProductViewSet": Route(
        COMPANY,
        "nested; the facility and the ingredient statement must be the URL's farm",
        outsider_tests=(
            "certifications.tests.test_facility_products.FacilityProductTenancyTests"
            ".test_another_company_reaches_nothing",
            "certifications.tests.test_facility_products.FacilityProductTenancyTests"
            ".test_another_farms_facility_or_document_fails_like_a_missing_one",
        ),
    ),
    "certifications.views.BrandOwnerViewSet": Route(
        COMPANY,
        "nested; admins and managers only; both documents must be the URL's farm",
        outsider_tests=(
            "certifications.tests.test_brand_owners.BrandOwnerTenancyTests.test_another_company_reaches_nothing",
            "certifications.tests.test_brand_owners.BrandOwnerTenancyTests"
            ".test_another_farms_document_fails_like_a_missing_one",
        ),
    ),
    "certifications.views.OperationContactViewSet": Route(
        COMPANY,
        "nested; admins and managers only; the farm is the URL's, never the body's",
        outsider_tests=(
            "certifications.tests.test_operation_contacts.OperationContactTenancyTests"
            ".test_another_company_reaches_nothing",
            "certifications.tests.test_operation_contacts.OperationContactTenancyTests"
            ".test_a_viewer_reads_nothing_and_writes_nothing",
        ),
    ),
    "certifications.views.CertifierInspectionViewSet": Route(
        COMPANY,
        "nested; admins and managers only; the report must be the URL's farm",
        outsider_tests=(
            "certifications.tests.test_certifier_inspections.InspectionTenancyTests"
            ".test_another_company_reaches_nothing",
            "certifications.tests.test_certifier_inspections.InspectionTenancyTests"
            ".test_another_farms_document_fails_like_a_missing_one",
        ),
    ),
    "certifications.views.CertifierNoticeViewSet": Route(
        COMPANY,
        "nested; admins and managers only; every file and the inspection must be the URL's farm",
        outsider_tests=(
            "certifications.tests.test_certifier_inspections.NoticeTenancyTests.test_another_company_reaches_nothing",
            "certifications.tests.test_certifier_inspections.NoticeTenancyTests"
            ".test_another_farms_files_and_inspection_fail_like_missing_ones",
        ),
    ),
    "certifications.views.ProductionEquipmentViewSet": Route(
        COMPANY,
        "nested; admins and managers only; establishment set from the URL",
        outsider_tests=(
            "certifications.tests.test_production_equipment.EquipmentTenancyTests"
            ".test_another_company_reaches_nothing",
        ),
    ),
    "certifications.views.SupplierViewSet": Route(
        COMPANY,
        "nested; admins and managers only; a certificate's document must be the URL's farm",
        outsider_tests=(
            "certifications.tests.test_supplier_register.SupplierTenancyTests.test_another_company_reaches_nothing",
            "certifications.tests.test_supplier_register.SupplierTenancyTests"
            ".test_another_farms_document_fails_like_a_missing_one",
        ),
    ),
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
    "certifications.views.certifier_review_lot_traceback": Route(
        ANONYMOUS, "review-link token, certifier audience; the link's farm and dossier window"
    ),
    "certifications.views.certifier_review_lot_traceback_search": Route(
        ANONYMOUS, "review-link token, certifier audience; the link's farm and dossier window"
    ),
    "certifications.views.certifier_review_traceback": Route(
        ANONYMOUS, "review-link token, certifier audience; the link's farm and dossier window"
    ),
    "certifications.views.certifier_review_traceback_search": Route(
        ANONYMOUS, "review-link token, certifier audience; the link's farm and dossier window"
    ),
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
            "company.tests.test_team_members.MemberTenancyTests.test_another_companys_membership_under_own_url_is_a_plain_404",
            "company.tests.test_team_members.MemberTenancyTests.test_outsider_admin_cannot_change_another_companys_team",
        ),
    ),
    "company.views.EstablishmentViewSet": Route(
        COMPANY,
        "queryset filter(company=self.company) + scope_to_caller_companies; every action fetches the "
        "farm through self.get_object(); ?parcel= and ?production= resolve inside the farm; "
        "validate_company refuses moving a farm on update",
        outsider_tests=(
            f"{_CROSS}.test_foreign_establishment_under_own_company_url",
            f"{_EST}.test_actions_refuse_another_companys_farm_under_own_company_url",
            f"{_EST}.test_patch_cannot_move_a_farm_into_another_company",
            f"{_EST}.test_query_params_cannot_probe_another_companys_ids",
        ),
    ),
    "company.views.ApplicatorViewSet": Route(
        COMPANY,
        "nested; queryset filter(company=self.company), so another company's id is a plain 404; the "
        "serializer has no company field, the view sets the URL's on create; members read, CA/FM "
        "write; DELETE deactivates",
        outsider_tests=(
            "company.tests.test_applicators.ApplicatorTenancyTests.test_another_company_reaches_nothing",
            "company.tests.test_applicators.ApplicatorTenancyTests"
            ".test_another_companys_applicator_is_the_same_404_as_a_missing_one",
            "company.tests.test_applicators.ApplicatorTenancyTests.test_company_in_the_body_is_ignored",
        ),
    ),
    "product.views.ParcelCropHistoryViewSet": Route(
        COMPANY,
        "queryset scoped to the caller's companies; the parcel FK accepts only the caller's parcels",
        outsider_tests=(f"{_FK}.test_crop_history_cannot_be_written_on_another_companys_parcel",),
    ),
    "product.views.ParcelPlannedCropViewSet": Route(
        COMPANY,
        "nested under the parcel; the parcel is the URL's and must be the URL's farm, never the body's",
        outsider_tests=(
            "product.tests.test_parcel_planned_crops.PlannedCropTenancyTests.test_another_company_reaches_nothing",
            "product.tests.test_parcel_planned_crops.PlannedCropTenancyTests"
            ".test_another_farms_parcel_reads_like_a_missing_one",
        ),
    ),
    "product.views.ParcelViewSet": Route(
        COMPANY,
        "queryset scoped to the caller's companies; CreateParcelSerializer.establishment accepts only "
        "the caller's farms (CallerScopedRelatedFields)",
        outsider_tests=(
            f"{_CROSS}.test_parcel_read_edit_delete",
            f"{_FK}.test_parcel_cannot_move_to_another_companys_farm",
            f"{_FK}.test_refusal_does_not_confirm_the_id_exists",
            f"{_FKR}.test_parcel_cannot_point_at_another_companys_season",
        ),
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
        "_scope_to_caller on get_queryset and get_object; create parcels scoped to the caller; on the "
        "flat route edits and deletes are role-checked against the event's company",
        outsider_tests=(
            f"{_FLATX}.test_outsider_cannot_touch_another_companys_event_on_the_flat_route",
            f"{_FLAT}.test_viewer_cannot_edit_or_delete_through_flat_routes",
        ),
        finding="within one company: a VIEWER can still CREATE events on the flat route /api/events/ "
        "(create is not an object-level action, so ReadOnlyForViewers.has_object_permission never runs)",
    ),
    "history.views.HistoryScanViewSet": Route(
        COMPANY,
        "scope_to_caller_companies",
        outsider_tests=(
            f"{_CROSS}.test_scan_read_and_delete",
            f"{_FLAT}.test_viewer_cannot_edit_or_delete_through_flat_routes",
            f"{_FLATX}.test_admin_of_a_cannot_delete_bs_scan_through_as_url",
        ),
    ),
    "history.views.HistoryViewSet": Route(
        COMPANY,
        "scope_to_caller_companies; writes check CA/FM; public_history is AllowAny and reviewed",
        outsider_tests=(
            f"{_CROSS}.test_season_retrieve_by_id_and_uuid",
            f"{_CROSS}.test_season_list_shows_only_own",
            f"{_SCANS}.test_outsider_cannot_read_another_companys_scans",
            f"{_SCANS}.test_naming_own_company_with_a_foreign_farm_returns_nothing",
            f"{_WA_EXPORT}.test_another_companys_user_is_refused_like_the_pur_export",
            "certifications.tests.test_materials_application_rows.TheFormsOfferThePlansMaterials."
            "test_another_company_cannot_read_it",
        ),
        finding="my_reviews returns the full owner HistorySerializer (events, members, operator) for any season "
        "the caller reviewed; reviews are limited to published seasons since #197, so this over-shares "
        "a public season rather than exposing a private one; download_qr_code by UUID is unscoped",
    ),
    "history.views.PublicHistoryScanViewSet": Route(
        ANONYMOUS,
        "shopper scans; a GenericViewSet, so only create and the declared actions are routed; "
        "create needs a published season; consent needs the scan's claim_token",
        outsider_tests=(
            f"{_PUBSCANS}.test_stranger_cannot_delete_read_or_edit_a_scan",
            f"{_PUBSCANS}.test_nobody_can_write_a_comment_onto_a_scan",
        ),
    ),
    "history.views.RecordsExportViewSet": Route(COMPANY, "nested only; any member role may export"),
    "history.views.SalesRecordViewSet": Route(
        COMPANY,
        "CA/FM on the production; foreign harvest events rejected; sale and lot traces scoped to the "
        "caller's CA/FM companies and the URL's farm",
        outsider_tests=(
            f"{_SALETRACE}.TraceAccessTests.test_a_foreign_sale_is_the_same_404_as_a_missing_one",
            f"{_LOTTRACE}.LotTraceAccessTests.test_a_foreign_pick_is_the_same_404_as_a_missing_one",
            f"{_LOTTRACE}.LotSearchTests.test_another_companys_lot_code_matches_nothing",
        ),
    ),
    "history.views.audit_export_by_uuid": Route(COMPANY, "WorksIn on the production's company (any role)"),
    # compare_products and UserFavoriteViewSet carried the two findings here (an unpublished
    # season served to any UUID holder; integer ids turned into public UUIDs). Both were retired
    # with their models in history 0254, which closed the findings.
    "history.views_consumer.ConsumerDashboardViewSet": Route(USER, "impact and shopping filtered on the user"),
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
        "non-superusers get filter(id=request.user.id); verify/reset actions are AllowAny. The email "
        "changes only through request_email_change (acts on request.user, needs the password) and "
        "confirm_email_change (AllowAny, proven by a hashed single-use token sent to the new address); "
        "the is_superuser self-escalation is fixed in #188, guard "
        "users.tests.test_user_privilege_fields_read_only",
        # Closed 2026-11-11 (overall review OV-SEC-C03): was "email changes without re-verification".
        outsider_tests=(
            "users.tests.test_account_takeover_chain.AccountTakeoverChainTests."
            "test_another_account_cannot_touch_this_one",
            "users.tests.test_account_takeover_chain.AccountTakeoverChainTests."
            "test_a_profile_patch_cannot_change_the_login_email",
            "users.tests.test_account_takeover_chain.AccountTakeoverChainTests."
            "test_requesting_a_change_needs_the_password",
        ),
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
        "reads scoped to the caller's tickets; the ticket and message FKs accept only the caller's",
        outsider_tests=(f"{_FK}.test_support_attachment_cannot_land_in_another_companys_ticket",),
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
    # QRSecurityHealthCheck, qr_security_info, security_metrics and validate_production_access were
    # REMOVED on 2026-11-13: anonymous, no caller anywhere. The health probe's finding (Secrets
    # Manager per request, str(e) to anonymous callers, and whether the QR signing key was the
    # fallback) closed with it.
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
UNPROVEN_CEILING = 48

# Declarations carrying a `finding`, any scope. Same rule: lower it as findings close.
OPEN_FINDINGS_CEILING = 16
