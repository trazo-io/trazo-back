from django.urls import include, path

from rest_framework.routers import DefaultRouter

from . import views, views_security_enhanced
from .views import (
    AutomationRuleViewSet,
    CarbonEstablishmentSummaryViewSet,
    CarbonProductionSummaryViewSet,
    CarbonProductionViewSet,
    PublicProductionViewSet,
    calculate_event_carbon_impact,
    calculate_event_carbon_impact_enhanced,
)

router = DefaultRouter()
# Database-driven Crop Template System
router.register(r"crop-types", views.CropTypeViewSet)
router.register(r"event-templates", views.EventTemplateViewSet)
router.register(r"sources", views.CarbonSourceViewSet)
router.register(r"offset-actions", views.CarbonOffsetActionViewSet)
router.register(r"entries", views.CarbonEntryViewSet)
router.register(r"certifications", views.CarbonCertificationViewSet)
# NEVER: 2026-09-30 - UNREGISTERED, and they must stay unregistered. Guard:
# `carbon/tests/test_retired_claim_routes_stay_retired.py`. Same decision as the badge routes
# below, reached the same way and for two reasons rather than one.
#
#   reports      `CarbonReport.carbon_score` WAS an IntegerField validated 0 to 100, labelled
#                "Score from 1 to 100" and served in the serializer's fields, written by
#                `generate_nightly_reports` as 100 * (1 - net_footprint / industry_average): a
#                self-assigned grade, comparative against an average this product computed about
#                itself, on a figure that netted offsets out of emissions. The task was deleted and
#                the column, its index and its serializer field were dropped in migration 0039, so
#                there is nothing left for this route to serve. It stays unregistered anyway,
#                because the route is the part that gets rediscovered and rewired.
#   benchmarks   `CarbonBenchmark.average_emissions` was the DENOMINATOR of that score, computed
#                from Trazo's own CarbonEntry rows. With no real users it would be an average of
#                demo and test data presented as an industry baseline. That model is still here.
#
# The second reason is tenancy, and it applies to `reports` regardless of the claim: the viewset
# was `queryset = CarbonReport.objects.all()` with `IsAuthenticated`, no `get_queryset` override
# and no filter backend, so any signed-in account could list every establishment's reports. The
# `?establishment=` parameter the frontend sent was never honoured. Empty today only because
# nothing writes rows, which is the same shape as the 2026-09-28 company-viewset finding.
#
# Both frontend callers were already dead, checked before unregistering: `getCarbonBenchmarks` in
# `trazo-app/src/store/api/carbonApi.ts` is declared and never called, and `getCarbonReports` in
# `companyApi.ts` has one consumer, `CarbonReportTab.jsx`, which is imported nowhere.
#
# On the models: `CarbonBenchmark` is left in place, following the 2026-09-07 precedent below, which
# kept models and cut routes. `CarbonReport` is also kept, but its `carbon_score` column WAS dropped,
# in migration 0039, because a route being closed is not a reason to keep a field whose only writer is
# gone and whose only meaning is a retired claim.
#
# 2026-09-30: THE TWO SIBLINGS THIS NOTE USED TO WARN ABOUT ARE NOW FIXED. It read: "two sites
# still compute a score of their own and are NOT fixed by any of this: `CarbonEntryViewSet.summary`
# returns `carbon_score` and `industry_average`, and `CarbonEstablishmentSummaryViewSet.summary`
# returns `carbon_score` plus a `performance_tier` label." Both payloads were cut, along with
# `_get_performance_tier`, which turned the number into a word, a COLOUR and a verdict sentence.
# Those routes STAY REGISTERED, because unlike the ones below they serve measured quantities that a
# grower needs; it was the grade on top that had to go. Guard:
# `carbon/tests/test_live_carbon_payloads_carry_no_grade.py`, which asserts payload SHAPE on a live
# route rather than the absence of a route, since that is the failure mode here.
#
# The same commit removed the premium-pricing claims those endpoints sat beside: a hardcoded
# `premium_percentage` of "10-15%" in `carbon/views.py`, and in
# `carbon/services/carbon_cost_insights.py` a four-rung none/basic/sustainable/premium ladder with a
# `potential_premium` string. compliance.md bans price and premium claims by name.
#
# 2026-09-30: that whole service file is gone, and with it the one route that reached it,
# `establishments/<id>/carbon-summary/`. What was left after the premium ladder came out was a
# carbon-credit REVENUE estimate (`potential_revenue` from a `market_rate_per_ton`) and advice
# to register with a carbon credit marketplace: the 16 CFR 260.5 offset class, in a module
# whose live route no frontend called. Its own docstring said the credit figure was "HIDDEN
# from UI", which is the pattern this file keeps recording: hidden is not retired.
#
# router.register(r"benchmarks", views.CarbonBenchmarkViewSet)
# router.register(r"reports", views.CarbonReportViewSet)
# ⛔ 2026-09-07 — UNREGISTERED, and they must stay unregistered. Guard:
# `carbon/tests/test_retired_claim_routes_stay_retired.py`.
#
#   badges         SustainabilityBadge is a self-assigned sustainability label — a grade this
#                  product awards itself. That is the class EU ECGT 2024/825 bans outright
#                  (live 2026-09-27) and the class `.claude/rules/transparency-first.md` already
#                  removed from every rendered surface. The endpoint outlived the widgets: it
#                  still served badge rows to any authenticated caller, with no UI behind it.
#   green-points   Gamification points. Same shape — a score we invent about ourselves.
#   micro-offsets  Consumer micro-offset purchases, from the pre-pivot offset marketplace.
#
# The MODELS are left in place: dropping tables is a separate decision with a migration, and the
# route is the part that can be rediscovered, linked, or wired into a surface by accident.
# Re-registering one of these is a product decision about claims, not a refactor.
#
# router.register(r"badges", views.SustainabilityBadgeViewSet)
# router.register(r"micro-offsets", views.MicroOffsetViewSet)
# router.register(r"green-points", views.GreenPointsViewSet)
router.register(r"audit-logs", views.CarbonAuditLogViewSet)
# ⛔ 2026-09-07 — UNREGISTERED for the same reason as the badge routes above. The carbon-offset
# marketplace (projects, purchases, certificates) is pre-pivot: Trazo measures direct operational
# emissions and makes no offset claim. "Certificate" is the sharpest word in the whole app for
# something nobody audits. No frontend hook referenced any of the three.
#
# router.register(r"offset-projects", views.CarbonOffsetProjectViewSet)
# router.register(r"offset-purchases", views.CarbonOffsetPurchaseViewSet)
# router.register(r"offset-certificates", views.CarbonOffsetCertificateViewSet)
router.register(r"calculator", views.CarbonFootprintCalculatorViewSet, basename="calculator")
router.register(r"establishments", CarbonEstablishmentSummaryViewSet, basename="carbon-establishment-summary")
router.register(r"productions", CarbonProductionSummaryViewSet, basename="carbon-production-summary")
router.register(r"public/productions", PublicProductionViewSet, basename="public-production")
# ⛔ 2026-09-07 — UNREGISTERED, and this was the worst of the set. `CarbonOffsetViewSet` has one
# action, `certified_projects`, which returns `CarbonOffsetProject.objects.all()` — the same
# marketplace model whose CRUD routes are retired above — and decorates each row with a
# hardcoded `verification_badges` dict containing the literal text "VCS Verified".
#
# That is a third-party verification claim, written by us, attached to our own rows, served to
# any authenticated caller. `.claude/rules/compliance.md` puts "verified" in the UNSAFE column
# for everything except a USDA Organic Integrity Database match. Retiring the CRUD routes while
# leaving this read door open would have been the "fixed on the audited surface, alive on its
# sibling" failure the audits keep re-finding.
#
# No frontend hook consumed it (`useGetCertifiedProjectsQuery`, `useCreateOffsetMutation`: zero
# call sites), and the viewset has no create action, so the POST those hooks aimed at was already
# a 405.
#
# router.register(r"offsets", views.CarbonOffsetViewSet, basename="carbon-offset")
router.register(r"productions-flat", CarbonProductionViewSet, basename="carbon-production-flat")
router.register(r"iot-devices", views.IoTDeviceViewSet, basename="iot-devices")
router.register(r"automation-rules", AutomationRuleViewSet, basename="automation-rules")
# ⛔ 2026-09-08 — UNREGISTERED. Guard:
# `carbon/tests/test_retired_claim_routes_stay_retired.py`.
#
# `BlockchainVerificationViewSet` served three actions, all of them claim-bearing and none of
# them reachable from any frontend:
#
#   POST verify-production/          "Production verified on blockchain"
#   GET  verify-record/<id>/         blockchain_service.verify_carbon_record(id)
#   GET  verify/<id>/                the same call, same response shape
#
# Three problems, any one of which is disqualifying:
#
#   1. WORDING. `.claude/rules/compliance.md` puts "blockchain-verified" in the UNSAFE column —
#      a hash shows a record was not altered after submission; it says nothing about whether the
#      farming practice happened. The POST action answered literally "Production verified on
#      blockchain".
#   2. NO OWNERSHIP CHECK. `History.objects.get(id=production_id)` against a raw body field. Any
#      authenticated user could name any production on the platform.
#   3. IT SHADOWED ITSELF. Two methods were both named `verify_production` (the POST at the top,
#      the GET further down). The second binding wins, so the POST action never registered at
#      all — the route advertised in the docstring had not existed for as long as both copies
#      have been in the file.
#
# Unlike the `blockchain/...` function routes below, this viewset ran on
# `carbon/services/blockchain.py`, which fails CLOSED — with the chain unavailable
# `verify_carbon_record` returns `{"verified": False}` rather than inventing a transaction. So it
# was not fabricating; it was wrapping a negative in `{"status": "success"}` and calling it
# verification. That is a wording and authorization defect, not a fabrication one, and it is
# retired on those grounds.
#
# The class itself is DELETED from views.py, so the line below will not work if uncommented —
# which is the intent. Restoring the route means rewriting the actions and deciding, out loud,
# what they are allowed to say.
#
# router.register(r"blockchain", views.BlockchainVerificationViewSet, basename="blockchain-verification")

urlpatterns = [
    path("", include(router.urls)),
    # Legacy endpoint (maintained for backward compatibility)
    path("calculate-event-impact/", calculate_event_carbon_impact, name="calculate-event-carbon-impact"),
    # High-performance Carbon Calculation Endpoint - 95% Performance Improvement
    path(
        "calculate-event-carbon/",
        calculate_event_carbon_impact_enhanced,
        name="calculate-event-carbon",
    ),
    # Enhanced USDA Integration Endpoints
    path("enhanced-event-impact/", views.calculate_event_impact, name="enhanced-event-impact"),
    path("usda-credibility/<int:establishment_id>/", views.get_usda_credibility_info, name="usda-credibility"),
    path("regional-benchmark/<int:establishment_id>/", views.get_regional_benchmark, name="regional-benchmark"),
    # NEW USDA API Endpoints (Month 1 Implementation)
    path("usda/validate-compliance/", views.validate_usda_compliance, name="usda-validate-compliance"),
    path("usda/regional-factors/<str:state>/", views.get_regional_emission_factors, name="usda-regional-factors"),
    path("usda/benchmark-comparison/", views.get_usda_benchmark_comparison, name="usda-benchmark-comparison"),
    path(
        "usda/compliance-history/<int:production_id>/",
        views.get_usda_compliance_history,
        name="usda-compliance-history",
    ),
    path("process-voice-event/", views.process_voice_event_ai, name="process-voice-event-ai"),
    # Deepgram voice transcription endpoints
    path("voice-config/", views.voice_config, name="voice-config"),
    path("deepgram-token/", views.deepgram_token, name="deepgram-token"),
    # AI-powered smart event suggestions
    path("ai-event-suggestions/", views.get_ai_event_suggestions, name="ai-event-suggestions"),
    path("webhooks/john-deere/", views.john_deere_webhook, name="john_deere_webhook"),
    path("webhooks/weather-station/", views.weather_station_webhook, name="weather_station_webhook"),
    # IoT Device Management
    path("iot-devices/", views.IoTDeviceViewSet.as_view({"get": "list", "post": "create"}), name="iot-devices"),
    path(
        "iot-devices/<int:pk>/",
        views.IoTDeviceViewSet.as_view({"get": "retrieve", "put": "update", "delete": "destroy"}),
        name="iot-device-detail",
    ),
    path("iot-devices/status/", views.IoTDeviceViewSet.as_view({"get": "device_status"}), name="iot-device-status"),
    path(
        "iot-devices/simulate_data/",
        views.IoTDeviceViewSet.as_view({"post": "simulate_data"}),
        name="iot-simulate-data",
    ),
    path(
        "iot-devices/pending_events/",
        views.IoTDeviceViewSet.as_view({"get": "pending_events"}),
        name="iot-pending-events",
    ),
    path(
        "iot-devices/approve_event/",
        views.IoTDeviceViewSet.as_view({"post": "approve_event"}),
        name="iot-approve-event",
    ),
    path(
        "iot-devices/reject_event/", views.IoTDeviceViewSet.as_view({"post": "reject_event"}), name="iot-reject-event"
    ),
    # John Deere API Integration
    path("john-deere/auth/", views.john_deere_auth_start, name="john_deere_auth_start"),
    path("john-deere/callback/", views.john_deere_auth_callback, name="john_deere_auth_callback"),
    path("john-deere/sync-devices/", views.john_deere_sync_devices, name="john_deere_sync_devices"),
    path("john-deere/webhook/", views.john_deere_webhook, name="john_deere_webhook"),
    # Weather API endpoints
    path("weather/current/", views.weather_current_conditions, name="weather_current_conditions"),
    path("weather/alerts/", views.weather_alerts, name="weather_alerts"),
    path("weather/recommendations/", views.weather_recommendations, name="weather_recommendations"),
    path("weather/forecast/", views.weather_forecast, name="weather_forecast"),
    path("weather/create-alert-event/", views.weather_create_alert_event, name="weather_create_alert_event"),
    # Carbon Cost Intelligence endpoints (simplified, carbon-focused only)
    path(
        "productions/<int:production_id>/economics/",
        views.get_production_carbon_economics,
        name="production_carbon_economics",
    ),
    # DISABLED: Carbon credits hidden from UI per transparency-first decision
    # path(
    #     "productions/<int:production_id>/carbon-credits/",
    #     views.get_carbon_credit_potential,
    #     name="carbon_credit_potential",
    # ),
    # Crop Templates API
    path("crop-templates/", views.get_crop_templates, name="crop-templates"),
    path("crop-templates/<str:template_id>/", views.get_crop_template_detail, name="crop-template-detail"),
    # Company Creation Crop Options (Production Ready)
    path("company-crop-options/", views.get_company_crop_options, name="company-crop-options"),
    # Educational content endpoints (Week 2)
    path("education/usda-methodology/", views.get_usda_methodology_content, name="usda-methodology-content"),
    path(
        "education/regional-practices/<str:state>/<str:crop_type>/",
        views.get_regional_farming_practices,
        name="regional-farming-practices",
    ),
    path(
        "education/carbon-examples/<str:carbon_value>/", views.get_carbon_impact_examples, name="carbon-impact-examples"
    ),
    path("education/trust-comparison/", views.get_trust_comparison_data, name="trust-comparison-data"),
    # Generic educational content endpoint
    path("education/<str:topic>/", views.get_education_content, name="education-content"),
    # ⛔ 2026-09-08 — UNREGISTERED, with the views and the whole
    # `carbon/services/production_blockchain.py` service deleted. Guard:
    # `carbon/tests/test_retired_claim_routes_stay_retired.py`.
    #
    # `BLOCKCHAIN_ENABLED=False` did NOT disable these. The flag is read once, in
    # `_initialize_blockchain_connection()`, and its only effect is to skip the Web3 connect and
    # leave `mock_mode = True`. Every one of these endpoints then fell through to a mock branch
    # that fabricated a successful result:
    #
    #   POST blockchain/batch-verify/  {"production_ids": [1, 2, 3]}
    #   -> 200 {"status": "completed", "success_rate": 100.0,
    #           "transaction_hashes": ["0x000...0", "0x000...0", "0x000...0"]}
    #
    # A live production endpoint answering "completed" with a fabricated transaction hash, for a
    # product Trazo does not sell, to any authenticated caller, for production ids it never
    # checked the caller owns. Nothing was persisted and no surface rendered it, so no false
    # evidence reached a consumer page — but a flag whose failure mode is "invent a plausible
    # answer" is the wrong failure mode. `blockchain/mint-credits/` was worse still: it took
    # `farmer_address` and `co2e_amount` straight from the request body and reported minted
    # carbon credit NFTs, which is the 16 CFR 260.5 carbon-offset claim class that the retired
    # `offset-projects` / `offset-purchases` / `offset-certificates` routes above were retired
    # for. Minting outlived the marketplace by one day.
    #
    # path("blockchain/batch-verify/", views.batch_verify_productions, ...)
    # path("blockchain/gas-analysis/", views.get_gas_optimization_analysis, ...)
    # path("blockchain/mint-credits/", views.mint_carbon_credits_batch, ...)
    # path("blockchain/service-stats/", views.get_blockchain_service_stats, ...)
    # path("blockchain/deploy-contract/", views.deploy_carbon_credit_contract, ...)
    # Third-Party Verification API Endpoints (NEW)
    path("verify-registry-credentials/", views.verify_registry_credentials, name="verify_registry_credentials"),
    path(
        "entries/<int:carbon_entry_id>/verification-status/",
        views.get_verification_status,
        name="get_verification_status",
    ),
    path("bulk-verify/", views.bulk_verify_entries, name="bulk_verify_entries"),
    path("methodology-templates/", views.get_methodology_templates, name="get_methodology_templates"),
    # Enhanced Security Endpoints
    path(
        "secure/create-carbon-offset/",
        views_security_enhanced.create_secure_carbon_offset,
        name="create_secure_carbon_offset",
    ),
    path(
        "secure/validate-file-upload/",
        views_security_enhanced.validate_file_upload_security,
        name="validate_file_upload_security",
    ),
    path(
        "secure/user-security-status/",
        views_security_enhanced.get_user_security_status,
        name="get_user_security_status",
    ),
    # Photo Evidence Service Endpoints
    path("evidence/upload/", views.upload_evidence_photo_enhanced, name="upload_evidence_photo_enhanced"),
    path(
        "evidence/<int:carbon_entry_id>/photos/",
        views.get_evidence_photos_enhanced,
        name="get_evidence_photos_enhanced",
    ),
    path("evidence/validate/", views.validate_photo_evidence, name="validate_photo_evidence"),
    # ⛔ 2026-09-08 — UNREGISTERED with the views and
    # `carbon/services/gas_optimized_blockchain.py` deleted. Polygon gas estimation for a chain
    # this product no longer writes to. Two RTK Query hooks existed for these two routes
    # (`estimateGasCosts`, `optimizeTransactionGas`) and neither had a single call site; they
    # were deleted from `trazo-app/src/store/api/carbonApi.ts` in the same change.
    #
    # path("blockchain/gas-estimate/", views.estimate_gas_costs, ...)
    # path("blockchain/optimize-transaction/", views.optimize_transaction_gas, ...)
    # Phase 6: Advanced Carbon Analytics Endpoint
    # Smart Product API Endpoints - Smart Bag UX Implementation
    path("smart-product/search/", views.smart_product_search, name="smart_product_search"),
    path("smart-product/validate/", views.smart_product_validation, name="smart_product_validation"),
    path(
        "smart-product/suggestions/", views.smart_product_suggestions_by_type, name="smart_product_suggestions_by_type"
    ),
    path("smart-product/stats/", views.smart_product_stats, name="smart_product_stats"),
]
