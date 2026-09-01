"""No self-graded score or unsubstantiated benefit claim may reach an anonymous consumer.

A scan of all 112 published productions on 2026-08-03 found **20 leaking** on
``GET /api/transparency/<public_id>/``: ``traceability_score`` (14 productions),
``biodiversity_score_improvement`` "+35%" (11), ``pesticide_reduction`` "90%" (11),
``pest_reduction_percentage`` (6), ``max_score`` (2), ``data_integrity_score`` (1).

Not a blocklist gap — ``ALLOWED_EXTRA_DATA_KEYS`` had grown to 447 entries and explicitly
admitted every one of them. An allow-list that large cannot be audited by eye, and seed and
template data keep inventing new claim-shaped keys, so the guard is a SHAPE match rather than
another key list.

Two distinct rules are at stake:

* A self-assigned **score** on a consumer surface is what the 2026-06 demotion removed and
  Trazo Test #5 forbids — the producer dashboard owns the score, shoppers get facts.
* "90% pesticide reduction" / "+35% biodiversity improvement" are quantified comparative
  benefit claims with no baseline and no third-party verification: FTC 16 CFR 260.6, and the
  self-created-label class EU ECGT 2024/825 bans from 2026-09-27.

Facts that merely *contain* a claim-ish word must survive — a harvest grade split
(``quality_grade_distribution: {"Premium": 85}``) is data about the crop, not a price promise.
"""

from django.test import TestCase

from history.serializers import PublicHistorySerializer

# Shapes that must never appear as an extra_data key on a consumer payload.
CLAIM_SHAPED_KEYS = [
    "traceability_score",
    "carbon_score",
    "data_integrity_score",
    "max_score",
    "score",
    "biodiversity_score_improvement",
    "pesticide_reduction",
    "pathogen_reduction",
    "pest_reduction_percentage",
    "pest_reduction_achieved",
    "soil_health_rating",
    "yield_vs_conventional",
    "annual_revenue",
    "farm_roi",
    "roi_percentage",
]


class _FakeEvent:
    def __init__(self, extra_data):
        self.extra_data = extra_data


def _sanitize(extra_data):
    return PublicHistorySerializer()._sanitize_extra_data_for_public(_FakeEvent(extra_data))


class ConsumerExtraDataClaimShapeTests(TestCase):
    def test_no_claim_shaped_key_survives_at_top_level(self):
        for key in CLAIM_SHAPED_KEYS:
            with self.subTest(key=key):
                out = _sanitize({key: "90%", "growth_stage": "budbreak"}) or {}
                self.assertNotIn(key, out, f"{key} reached the anonymous consumer payload")

    def test_claim_shapes_are_blocked_even_if_allow_listed(self):
        """The allow-list is not the last word — the shape guard runs after it.

        Every key below IS in ALLOWED_EXTRA_DATA_KEYS; that is exactly how they leaked.
        """
        allow_listed_claims = [
            k
            for k in ("traceability_score", "pesticide_reduction", "biodiversity_score_improvement")
            if k in PublicHistorySerializer.ALLOWED_EXTRA_DATA_KEYS
        ]
        self.assertTrue(allow_listed_claims, "expected these to still be present in the allow-list")
        for key in allow_listed_claims:
            with self.subTest(key=key):
                self.assertNotIn(key, _sanitize({key: 99}) or {})

    def test_claim_shapes_are_blocked_inside_nested_objects(self):
        """The allow-list only ever gated top-level keys.

        `quality_grade_distribution` is allow-listed, so before this its whole sub-object
        shipped verbatim — a seed writing a claim one level down published it untouched.
        """
        out = _sanitize(
            {
                "quality_grade_distribution": {
                    "Premium": 85,
                    "pesticide_reduction": "90%",
                    "nested": {"traceability_score": 99, "keep_me": "yes"},
                }
            }
        )
        dist = (out or {}).get("quality_grade_distribution", {})
        self.assertNotIn("pesticide_reduction", dist)
        self.assertNotIn("traceability_score", dist.get("nested", {}))

    def test_legitimate_facts_survive(self):
        """A grade split is a fact about the crop, not a price or a grade of virtue."""
        out = _sanitize(
            {
                "quality_grade_distribution": {"Premium": 85, "Standard": 15},
                "nested": {"keep_me": "yes"},
                "growth_stage": "budbreak",
            }
        )
        self.assertEqual(out["quality_grade_distribution"], {"Premium": 85, "Standard": 15})
        self.assertEqual(out.get("growth_stage"), "budbreak")

    def test_certifier_only_fields_are_still_stripped_at_depth(self):
        """The worker-safety strip must apply inside nested objects too."""
        out = _sanitize({"quality_grade_distribution": {"rei_hours": 4, "Premium": 85}})
        self.assertNotIn("rei_hours", out["quality_grade_distribution"])

    def test_deeply_nested_structures_do_not_recurse_forever(self):
        payload = {"quality_grade_distribution": {}}
        node = payload["quality_grade_distribution"]
        for _ in range(12):
            node["child"] = {}
            node = node["child"]
        self.assertIsNotNone(_sanitize(payload))

    def test_no_new_claim_shaped_key_is_added_to_the_allow_list(self):
        """Fails the build if someone allow-lists a claim shape again.

        The shape guard already neutralises it, but an entry here means a future refactor that
        trusts the allow-list alone would republish the claim.
        """
        shapes = ("score", "_reduction", "reduction_", "_improvement", "_rating", "yield_vs_", "revenue", "_roi")
        offenders = sorted(
            k for k in PublicHistorySerializer.ALLOWED_EXTRA_DATA_KEYS if any(s in k.lower() for s in shapes)
        )
        # These 10 are the known historical entries; the guard blocks them at serialization.
        # A NEW one appearing here is what this test is for.
        known = {
            "biodiversity_score_improvement",
            "carbon_score",
            "data_integrity_score",
            "max_score",
            "pathogen_reduction",
            "pest_reduction_achieved",
            "pest_reduction_percentage",
            "pesticide_reduction",
            "score",
            "traceability_score",
        }
        self.assertEqual(
            set(offenders) - known,
            set(),
            "a new claim-shaped key was added to ALLOWED_EXTRA_DATA_KEYS — consumer surfaces "
            "show facts, not self-assigned grades (Trazo Test #5, FTC 260.6, EU ECGT)",
        )


class NamedClaimFieldsAreNotAllowListedTests(TestCase):
    """Some claim fields carry the claim in their PURPOSE, not in a matchable name.

    `trust_impact` and `transparency_benefit` are free text in which a grower states what
    trust or environmental benefit an event delivers -- a self-created sustainability claim
    (FTC 16 CFR 260.6; EU ECGT 2024/825 from 2026-09-27). Neither name matches any substring
    in `EXTRA_DATA_SENSITIVE_SUBSTRINGS`, so the 2026-08-03 shape guard could not see them and
    both stayed allow-listed onto the anonymous payload until 2026-08-31.

    Nothing collected them -- no BusinessTab input, no display registry entry, no renderer on
    any surface -- so this closes an exposure rather than removing a feature. The write path
    in `BusinessEventSerializer.to_internal_value` is deliberately kept: a value an API client
    sends is still filed, it is simply never published.

    Asserted against the allow-list itself, not through `_sanitize`, because the shape guard
    genuinely cannot catch these; membership is the only thing keeping them out.
    """

    NAMED_CLAIM_FIELDS = ("trust_impact", "transparency_benefit")

    def test_named_claim_fields_are_absent_from_the_allow_list(self):
        for key in self.NAMED_CLAIM_FIELDS:
            with self.subTest(key=key):
                self.assertNotIn(
                    key,
                    PublicHistorySerializer.ALLOWED_EXTRA_DATA_KEYS,
                    f"{key} is a grower-authored benefit claim; allow-listing it publishes it "
                    "to shoppers, and no substring in EXTRA_DATA_SENSITIVE_SUBSTRINGS will "
                    "catch it on the way out",
                )

    def test_the_shape_guard_alone_would_not_have_caught_them(self):
        """The two defences must not silently overlap.

        Not a non-vacuity proof of the test above -- that was established by re-adding the
        keys to the allow-list and watching it fail. This pins the REASON that test has to
        exist: the shape guard cannot see these names, so allow-list membership is the only
        thing keeping them out. If a future edit makes them shape-matchable, this fails and
        the test above becomes redundant -- the moment to simplify, not to widen the
        allow-list.
        """
        substrings = PublicHistorySerializer.EXTRA_DATA_SENSITIVE_SUBSTRINGS
        for key in self.NAMED_CLAIM_FIELDS:
            with self.subTest(key=key):
                self.assertFalse(
                    any(sub in key.lower() for sub in substrings),
                    f"{key} now matches the shape guard, so allow-list membership is no longer "
                    "the only thing keeping it out",
                )

    def test_they_do_not_reach_the_public_payload(self):
        out = (
            _sanitize(
                {
                    "trust_impact": "Builds enormous consumer trust in our sustainable methods",
                    "transparency_benefit": "Proves our environmental leadership",
                    "growth_stage": "budbreak",
                }
            )
            or {}
        )
        self.assertNotIn("trust_impact", out)
        self.assertNotIn("transparency_benefit", out)
        # A legitimate neighbour still survives, so the test cannot pass by sanitising away
        # everything.
        self.assertIn("growth_stage", out)
