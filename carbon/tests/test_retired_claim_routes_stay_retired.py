"""
Routes that were retired because of what they CLAIM, not because they were unused.

Unused is why they were easy to remove. It is not why they had to go.

`SustainabilityBadge` is a grade this product awards itself. EU ECGT 2024/825 (live 2026-09-27)
bans self-created sustainability labels without third-party verification, and
`.claude/rules/transparency-first.md` had already pulled every badge widget off every rendered
surface. What survived that removal was the API: `GET /api/carbon/badges/` still returned badge
rows to any authenticated caller, with nothing in front of it. `green-points` is the same shape
with a different noun. The offset marketplace — projects, purchases, and a route literally called
`offset-certificates` — is pre-pivot: Trazo measures direct operational emissions and makes no
offset claim, so a "certificate" endpoint is the sharpest unearned word in the codebase.

The audit that found them (`documentation/audits/CARBON_SURFACE_AUDIT_2026-09-07.md`) also found
why this is worth a test rather than a delete: **a route is the part that gets rediscovered.**
Six months from now the models are still there, the serializers are still there, and the viewsets
are still there — someone wiring a dashboard finds `SustainabilityBadgeViewSet`, registers it in
four characters, and the claim is back with no discussion. Re-registering one of these is a
product decision about what Trazo asserts, and this test is where that decision has to be made
out loud.

The models are deliberately NOT dropped. That is a separate call with a migration behind it, and
it is not the part that leaks.

2026-09-08 — the blockchain tranche joined them, and it taught the sharper half of the lesson:
**a feature flag set to False is not a retired route.** `BLOCKCHAIN_ENABLED` had defaulted False
since 2026-08-06 and the $15/mo add-on was withdrawn on 2026-08-03, and every one of these
endpoints was still live and still answering 200. The flag was read in exactly one place —
`ProductionBlockchainService._initialize_blockchain_connection()` — where its only effect was to
skip the Web3 connect and leave `mock_mode = True`. The endpoints then fell through to mock
branches that fabricated success:

    POST /api/carbon/blockchain/batch-verify/  {"production_ids": [1, 2, 3]}
    -> 200 {"status": "completed", "success_rate": 100.0,
            "transaction_hashes": ["0x000...0", "0x000...0", "0x000...0"]}

Nothing was persisted and no surface rendered it, so no false evidence reached a consumer page.
But a flag whose failure mode is "invent a plausible answer" is the wrong failure mode, none of
these views checked that the caller owned the production ids it named, and
`blockchain/mint-credits/` reported minted carbon credit NFTs from a `farmer_address` and a
`co2e_amount` taken straight off the request body — the 16 CFR 260.5 carbon-offset claim class
the offset routes above were retired for, one day earlier. Minting outlived the marketplace.

The services behind them are deleted outright (`production_blockchain`, `gas_optimized_blockchain`,
`multisig_blockchain_service`, `enhanced_multisig_blockchain_service`,
`multisig_blockchain_enhanced`, `blockchain_with_circuit_breaker` — 3858 lines, no importer
outside their own tests). `carbon/services/blockchain.py` is KEPT: it writes the finalization hash
the certifier packet's integrity line cites, and `backend/settings/base.py` records a deliberate
2026-08 decision to keep the restore path. That decision covers one module, not seven.
"""

from django.test import SimpleTestCase
from django.urls import NoReverseMatch, Resolver404, get_resolver, resolve, reverse

#: route prefix -> why it may not come back.
RETIRED_CLAIM_ROUTES = {
    "badges": (
        "SustainabilityBadge: a self-assigned sustainability grade. EU ECGT 2024/825 bans "
        "self-created sustainability labels without third-party verification; the widgets were "
        "removed in 2026-08 and this endpoint outlived them."
    ),
    "reports": (
        "CarbonReport.carbon_score: an IntegerField validated 0 to 100, labelled 'Score from 1 to "
        "100', in the serializer's fields, written nightly as 100 * (1 - net_footprint / "
        "industry_average). A self-assigned grade, comparative against an average we compute about "
        "ourselves, on a figure that nets offsets out of emissions. Second, independent reason: the "
        "viewset was objects.all() with IsAuthenticated and no company scoping, so it listed every "
        "establishment's reports to any signed-in account."
    ),
    "benchmarks": (
        "CarbonBenchmark.average_emissions: the denominator of that score, computed from Trazo's "
        "own CarbonEntry rows. An industry baseline we invent from our own data, which at zero "
        "real users means demo and test data."
    ),
    "green-points": (
        "GreenPoints: gamification score Trazo invents about itself. Same class as badges — a "
        "grade with the number filed off is still a grade."
    ),
    "micro-offsets": (
        "MicroOffset: consumer micro-offset purchases from the pre-pivot offset marketplace. "
        "Trazo makes no offset claim."
    ),
    "offset-projects": "CarbonOffsetProject: pre-pivot offset marketplace. No offset claim is made.",
    "offset-purchases": "CarbonOffsetPurchase: pre-pivot offset marketplace. No offset claim is made.",
    "offsets": (
        "CarbonOffsetViewSet.certified_projects: served CarbonOffsetProject rows decorated with a "
        "hardcoded verification_badges dict reading 'VCS Verified'. A third-party verification "
        "claim we wrote ourselves about our own rows — the UNSAFE column of compliance.md."
    ),
    "offset-certificates": (
        "CarbonOffsetCertificate: a 'certificate' nobody audits, issued by us, about us. The "
        "single strongest unearned word the carbon app ever exposed."
    ),
}

#: Exact paths, for routes that were plain `path()` entries rather than router prefixes.
#: Kept apart from RETIRED_CLAIM_ROUTES because those are probed as `/api/carbon/<prefix>/` and
#: these have segments of their own.
#:
#: The two `blockchain/verify...` entries are here rather than in the prefix dict for a reason
#: worth keeping: `BlockchainVerificationViewSet` was a bare `viewsets.ViewSet` with no `list`
#: method, so a DefaultRouter never generated `/api/carbon/blockchain/` at all. Probing that URL
#: would have 404'd whether or not the viewset was registered — a check that passes vacuously in
#: both directions. Its `@action` paths are the only URLs it ever actually had.
RETIRED_CLAIM_PATHS = {
    "blockchain/batch-verify/": (
        "batch_verify_productions: answered 200 {'status': 'completed', 'transaction_hashes': "
        "['0x000...0', ...]} out of ProductionBlockchainService's mock branch, for any "
        "production ids an authenticated caller named, with no ownership check."
    ),
    "blockchain/mint-credits/": (
        "mint_carbon_credits_batch: reported minted carbon credit NFTs from a farmer_address and "
        "a co2e_amount read straight off the request body. 16 CFR 260.5 carbon-offset claim "
        "class — the same one offset-projects/-purchases/-certificates were retired for."
    ),
    "blockchain/gas-analysis/": (
        "get_gas_optimization_analysis: Polygon gas modelling for a chain this product no longer "
        "writes to. Deleted with carbon/services/gas_optimized_blockchain.py."
    ),
    "blockchain/service-stats/": (
        "get_blockchain_service_stats: reported success_rate and contracts_loaded for a service "
        "that was permanently in mock mode. A status page for a withdrawn product."
    ),
    "blockchain/deploy-contract/": (
        "deploy_carbon_credit_contract: staff-gated smart contract deployment, signing with the "
        "platform's hot Polygon key. The add-on is withdrawn and BLOCKCHAIN_PRIVATE_KEY has been "
        "removed from the environment; there is nothing left to deploy and nothing to sign with."
    ),
    "blockchain/gas-estimate/": (
        "estimate_gas_costs: gas estimation for a withdrawn product. Its RTK Query hook "
        "(estimateGasCosts) existed with zero call sites and was deleted in the same change."
    ),
    "blockchain/optimize-transaction/": (
        "optimize_transaction_gas: as above (optimizeTransactionGas, also zero call sites)."
    ),
    "blockchain/verify-record/1/": (
        "BlockchainVerificationViewSet.verify_record: answered 'verified' from "
        "verify_carbon_record(), which returns True when a record merely EXISTS on chain without "
        "comparing it to current data. compliance.md puts 'blockchain-verified' in the UNSAFE "
        "column: a hash shows a record was not altered, not that a farming practice happened."
    ),
    "blockchain/verify/1/": (
        "BlockchainVerificationViewSet.verify_production: a byte-for-byte duplicate of "
        "verify-record above, and the second of two methods in that class that were BOTH named "
        "verify_production — so the POST action the class docstring advertised had never "
        "registered at all. Two readings of one route: you get the weaker one."
    ),
}

#: The DRF basenames those routers would have produced. Kept separate from the prefixes because
#: names and paths are two different doors a route can come back through.
#:
#: ⛔ Checked with `get_resolver().reverse_dict` membership, NOT with `reverse()`. `reverse(name)`
#: with no arguments raises `NoReverseMatch` for any route that takes one — verified against the
#: live `usda-credibility` — so a `reverse()`-based check would report
#: `blockchain-verification-verify-record` and `-verify-production` as retired even with both
#: registered and serving. Those two take a `production_id`. That is precisely the vacuous pass
#: this module's own docstring warns about, arriving through a second door.
RETIRED_ROUTE_NAMES = (
    "sustainabilitybadge-list",
    "greenpoints-list",
    "microoffset-list",
    "carbonoffsetproject-list",
    "carbonoffsetpurchase-list",
    "carbonoffsetcertificate-list",
    "carbon-offset-list",
    "carbon-offset-certified-projects",
    # blockchain tranche, 2026-09-08
    "blockchain-verification-verify-record",
    "blockchain-verification-verify-production",
    "batch_verify_productions",
    "mint_carbon_credits_batch",
    "gas_optimization_analysis",
    "blockchain_service_stats",
    "deploy_carbon_credit_contract",
    "estimate_gas_costs",
    "optimize_transaction_gas",
)


class RetiredClaimRoutesTests(SimpleTestCase):
    def test_every_retired_prefix_has_a_written_reason(self):
        """The register is the point. A prefix listed with a shrug is not a decision."""
        for prefix, reason in RETIRED_CLAIM_ROUTES.items():
            with self.subTest(route=prefix):
                self.assertGreater(
                    len(reason.strip()),
                    60,
                    "say what the route claimed and which rule it fell foul of, not just 'unused'",
                )

    def test_every_retired_path_has_a_written_reason(self):
        for route, reason in RETIRED_CLAIM_PATHS.items():
            with self.subTest(route=route):
                self.assertGreater(
                    len(reason.strip()),
                    60,
                    "say what the route claimed and which rule it fell foul of, not just 'unused'",
                )

    def test_the_retired_paths_do_not_resolve(self):
        still_routed = []
        for route in RETIRED_CLAIM_PATHS:
            try:
                match = resolve(f"/api/carbon/{route}")
            except Resolver404:
                continue
            still_routed.append(f"/api/carbon/{route} -> {match.func}")
        self.assertEqual(
            still_routed,
            [],
            "A retired blockchain route is registered again. BLOCKCHAIN_ENABLED=False does NOT "
            "make one of these safe — that flag only puts the service into mock mode, which is "
            "how they came to answer 200 with fabricated transaction hashes in the first place. "
            "Read this module's docstring:\n  " + "\n  ".join(still_routed),
        )

    def test_the_retired_routes_do_not_resolve(self):
        still_routed = []
        for prefix in RETIRED_CLAIM_ROUTES:
            try:
                match = resolve(f"/api/carbon/{prefix}/")
            except Resolver404:
                continue
            still_routed.append(f"/api/carbon/{prefix}/ -> {match.func}")
        self.assertEqual(
            still_routed,
            [],
            "A retired claim route is registered again. Removing it is not a refactor to undo — "
            "read this module's docstring, and if the claim really is wanted, delete its entry "
            "from RETIRED_CLAIM_ROUTES in the same change that registers it:\n  " + "\n  ".join(still_routed),
        )

    def test_the_retired_route_names_are_not_registered(self):
        """The other door: a viewset re-registered under any prefix restores these names."""
        registered_names = get_resolver().reverse_dict
        back = [name for name in RETIRED_ROUTE_NAMES if name in registered_names]
        self.assertEqual(
            back,
            [],
            "retired routes are registered again under these names:\n  " + "\n  ".join(back),
        )

    def test_the_checks_above_can_actually_fail(self):
        """A negative assertion has to prove it read something.

        Every check above is satisfied by a URLconf that failed to load, and the name check is
        also satisfied by a typo in RETIRED_ROUTE_NAMES — a misspelled name is absent from
        `reverse_dict` for the wrong reason and the test passes vacuously. So exercise each
        mechanism against a route that IS live. If any line here breaks, the checks above are
        proving nothing and must be fixed before they are trusted.
        """
        registered_names = get_resolver().reverse_dict

        # 1. router prefix, the form RETIRED_CLAIM_ROUTES probes
        match = resolve("/api/carbon/entries/")
        self.assertEqual(match.url_name, "carbonentry-list")
        self.assertIn("carbonentry-list", registered_names)

        # 2. multi-segment path, the form RETIRED_CLAIM_PATHS probes — a different branch of the
        #    URLconf than a bare router prefix.
        deep = resolve("/api/carbon/entries/1/verification-status/")
        self.assertEqual(deep.url_name, "get_verification_status")

        # 3. a live route that TAKES AN ARGUMENT, which is why the name check uses reverse_dict
        #    rather than reverse(). Two of the retired names are action routes with a
        #    production_id; if this ever regresses to reverse(), those two go silently vacuous.
        self.assertIn("usda-credibility", registered_names)
        with self.assertRaises(NoReverseMatch):
            reverse("usda-credibility")
