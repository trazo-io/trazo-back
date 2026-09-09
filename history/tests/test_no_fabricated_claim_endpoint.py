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
    "Iowa corn farm",
    # ✅ 2026-09-08, second pass: the unsourced statistics in `educational_content_service.py` are
    # now fixed, so these graduate from "documented exclusion" to enforced. That service is
    # reachable from `views/Scan/ProductDetail` via the education modal, i.e. by a shopper.
    "more efficient than the national average",
    "more carbon-efficient than the national average",
    "better carbon efficiency than the national average",
    "lead the nation",
    # A 0-100 carbon grade with verdict words, served by the deleted `carbon-scoring` topic:
    # "Your product scored {n}/100" … "excellent / good / average / below average".
    "most climate-friendly option in its category",
    "get_carbon_scoring_content",
)

# ⛔ THREE strings from that endpoint are deliberately NOT here, and the reasons matter:
#
# · `blockchain_verified` — an extra_data KEY that ~20 shipped modules read, including
#   `claim_authority.py`, which reads it in order to REFUSE the claim. Banning the string would
#   stop the refusal logic from naming what it refuses: the same "a guard that forbids naming what
#   it removed" trap that broke two other guards written today.
#
# · "USDA-verified" — the phrase IS on compliance.md's forbidden list, and it appears in ~15 shipped
#   modules (`carbon/views.py`, `emission_factors.py`, `calculator.py`, `transparency_views.py`,
#   several seeders). That is a vocabulary sweep of its own, not this endpoint's residue, and a guard
#   that fails on arrival gets skipped. SEPARATE OPEN FINDING — do not let this be its only record.
#
# · "Complete supply chain transparency" — still present in two demo SEEDERS' console output and
#   seeded data. Not enforced here yet because the seeders are a separate surface with their own
#   decision (what a demo dataset may assert), and a guard that fails on arrival gets skipped.
#
# ✅ RESOLVED 2026-09-08 (second pass): the unsourced-statistics cluster in
#   `educational_content_service.py` that this comment used to defer is FIXED, and those claim
#   shapes are now enforced above. What was there: "California citrus operations are 5% more
#   efficient than the national average", "33% less water per nut than 20 years ago", six invented
#   `adoption_rate` survey figures, four `efficiency_rank` state rankings, and a whole
#   `carbon-scoring` topic serving "Your product scored {n}/100" with
#   "excellent / good / average / below average". All reachable from the consumer product page.

#: Directories that hold shipped code. Excludes tests (this file quotes the claims on purpose).
CODE_DIRS = ("carbon", "history", "company", "product", "users", "subscriptions", "certifications", "documents")


def _without_comments(source: str) -> str:
    """Drop `#` comments before matching.

    ⚠️ Written after this guard failed on its OWN documentation three times in one afternoon: a
    comment explaining that "California citrus operations are 5% more efficient than the national
    average" was REMOVED contains the claim, and a guard that forbids naming what it removed makes
    the removal undocumentable. String literals are still scanned — that is where a served claim
    actually lives.
    """
    out = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


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
                text = _without_comments(path.read_text(encoding="utf-8", errors="ignore"))
                for claim in FABRICATED_CLAIMS:
                    if claim in text:
                        offenders.append(f"{path.relative_to(BACKEND)}: {claim}")
        self.assertEqual(
            offenders,
            [],
            "A fabricated claim from the deleted analytics endpoint is back in shipped code. "
            f"These assert verification that does not exist: {offenders}",
        )

    def test_the_education_service_declares_no_invented_survey_figures(self):
        """`adoption_rate` / `efficiency_rank` as DATA, not as identifiers.

        ⚠️ Narrowed after the bare identifiers flagged `carbon/services/verification_service.py`,
        where `adoption_rate` is genuinely COMPUTED — `similar_offsets /
        total_establishments_in_region` — and feeds the § additionality common-practice test. Banning
        the name would have outlawed a real measurement to catch invented strings.

        What was invented, in `educational_content_service.py`: six `"adoption_rate": "78%"`-shaped
        literals and four `"efficiency_rank": 1` state rankings, none with a source, all reachable
        from the consumer product page through the education modal.
        """
        service = (BACKEND / "carbon" / "services" / "educational_content_service.py").read_text(encoding="utf-8")
        code = _without_comments(service)
        for shape in ('"adoption_rate":', '"efficiency_rank":'):
            self.assertNotIn(
                shape,
                code,
                f"{shape} is back as data in educational_content_service.py. A percentage nobody "
                "sourced is not a survey, and a state ranking is a self-assigned grade.",
            )

    def test_the_carbon_grade_topic_stays_gone(self):
        """The `carbon-scoring` topic served a 0-100 grade with verdict words to shoppers."""
        from carbon.services.educational_content_service import EducationalContentService

        self.assertFalse(
            hasattr(EducationalContentService, "get_carbon_scoring_content"),
            "get_carbon_scoring_content is back. It served 'Your product scored {n}/100' and "
            "'excellent / good / average / below average' — a grade, on a consumer surface.",
        )
        # And the topic must fall through to the neutral fallback rather than resolve.
        content = EducationalContentService().get_educational_content("carbon-scoring", "beginner", {})
        self.assertNotIn("/100", str(content))

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
