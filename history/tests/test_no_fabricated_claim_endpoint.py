"""No endpoint may serve invented claims. Deleted 2026-09-08; this stops it coming back.

🔴 `GET /api/carbon/analytics/<production_id>/` was live and `IsAuthenticated`, served by
`carbon.views.advanced_carbon_analytics` → `AdvancedCarbonAnalyticsSerializer` →
`carbon/services/advanced_analytics.py`. Nothing in the product called it: the RTK endpoint
`getAdvancedAnalytics` had no call site. It returned, hardcoded, for any crop on any farm:

- "This corn production removes more CO2 from the atmosphere than it produces!"
- "This **Iowa corn farm** practices revolutionary sustainable agriculture…"
- `"third_party_audited": True` — Trazo performs no third-party audit
- `"blockchain_verified": True` — `BLOCKCHAIN_ENABLED=False`, add-on withdrawn, and
  "blockchain-verified" is on `compliance.md`'s forbidden list
- `"trust_score": 98` with the comment "# Very high trust score"
- `"Perfect Carbon Score (100/100)"`, `"Carbon Negative Production"`,
  `"Climate-Positive Agriculture"`, `"USDA-Verified Practices"`
- `"Complete supply chain transparency"` — the carbon boundary EXCLUDES the supply chain
- `"transparency_score"` — a FIFTH independent formula
- `peer_ranking` with `"out_of": 250` hardcoded

Every line violates a rule in `compliance.md`, and several assert third-party verification that
does not exist — the most dangerous claim shape there is. The whole endpoint, serializer and
942-line service were deleted rather than corrected: the values were invented, so there was nothing
to correct them to.

⛔ The lesson is not "delete demo code". It is that **an endpoint nobody calls is still published.**
`IsAuthenticated` hid it from every anonymous-payload sweep, and having no frontend caller hid it
from every UI review. A JSON response is a claim whether or not a component renders it.
"""

from pathlib import Path

from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse

BACKEND = Path(__file__).resolve().parents[2]

#: Strings that were hardcoded into that endpoint. None may reappear anywhere in the backend.
FABRICATED_CLAIMS = (
    "third_party_audited",
    "Perfect Carbon Score",
    "Carbon Negative Production",
    "Climate-Positive Agriculture",
    "USDA-Verified Practices",
    "Very high trust score",
)

# ⛔ THREE strings from that endpoint are deliberately NOT here, and the reasons matter:
#
# · `blockchain_verified` — an extra_data KEY that ~20 shipped modules read, including
#   `claim_authority.py`, which reads it in order to REFUSE the claim. Banning the string would
#   stop the refusal logic from naming what it refuses: the same "a guard that forbids naming what
#   it removed" trap that broke two other guards written today.
#
# · "Iowa corn farm" and "Complete supply chain transparency" — these DO still exist, in
#   `carbon/services/educational_content_service.py` and two demo seeders, and they are a SEPARATE
#   OPEN FINDING, not this endpoint's residue. That service is wired into five live view call sites
#   in `carbon/views.py` and serves a cluster of unsourced statistics: "California citrus operations
#   are 5% more efficient than the national average", "33% less water per nut than 20 years ago",
#   "Sustainable farms use 30% less water on average", "Diverse farms support 50% more beneficial
#   insects". Sourcing or deleting those is a content decision, so it is not silently folded in
#   here — and this guard is NOT weakened to hide them. Track it; do not let this comment be the
#   only record.

#: Directories that hold shipped code. Excludes tests (this file quotes the claims on purpose).
CODE_DIRS = ("carbon", "history", "company", "product", "users", "subscriptions", "certifications", "documents")


class NoFabricatedClaimEndpointTests(SimpleTestCase):
    def test_the_analytics_route_is_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse("advanced_carbon_analytics")

    def test_the_fabrication_service_is_gone(self):
        self.assertFalse(
            (BACKEND / "carbon" / "services" / "advanced_analytics.py").exists(),
            "carbon/services/advanced_analytics.py is back. It generated hardcoded claims of "
            "third-party audit, blockchain verification and a Perfect Carbon Score for any farm.",
        )

    def test_no_shipped_module_contains_those_claims(self):
        offenders = []
        for directory in CODE_DIRS:
            root = BACKEND / directory
            if not root.exists():
                continue
            for path in root.rglob("*.py"):
                parts = set(path.parts)
                if "tests" in parts or "migrations" in parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for claim in FABRICATED_CLAIMS:
                    if claim in text:
                        offenders.append(f"{path.relative_to(BACKEND)}: {claim}")
        self.assertEqual(
            offenders,
            [],
            "A fabricated claim from the deleted analytics endpoint is back in shipped code. "
            f"These assert verification that does not exist: {offenders}",
        )

    def test_the_scan_actually_read_files(self):
        """A negative assertion must prove it looked at something.

        Without this, a wrong `BACKEND` path or an over-eager exclude would make the sweep above
        pass by reading zero files — the vacuous-pass failure mode this repo keeps hitting.
        """
        scanned = sum(
            1
            for directory in CODE_DIRS
            if (BACKEND / directory).exists()
            for path in (BACKEND / directory).rglob("*.py")
            if "tests" not in set(path.parts) and "migrations" not in set(path.parts)
        )
        self.assertGreater(scanned, 200, f"only {scanned} modules scanned — the sweep is not looking where it thinks")
