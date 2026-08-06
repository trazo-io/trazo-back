"""
Unit tests for TransparencyCalculator — the producer-dashboard score.

Written 2026-08-04. Before this file the calculator had NO tests at all: the category weights,
the three-tier photo multipliers, the zero-event guard and the <3-event cap were entirely
unpinned, and the only file that exercised the class was a root-level demo script that pytest
never collects. That mattered more than usual because the same sprint moved the score off the
farm dashboard and onto a single page — a metric with one remaining home needs its arithmetic
held still, and the anti-gaming rules are the part a grower could otherwise game by logging one
event and an "organic" note.

These tests are deliberately DB-free. `_calculate_completeness_score` takes a plain
category-breakdown dict, and the cap logic is reachable by patching the two counting helpers, so
nothing here needs an Establishment/Parcel/History chain. That also sidesteps the fixture trap
recorded on 2026-08-02, where an Establishment built without `state` poisoned an atomic block
via NOT NULL on USDAComplianceRecord.state and looked like three unrelated failing suites.
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from history.services.transparency_calculator import TransparencyCalculator


def breakdown(**category_scores):
    """Build a category_breakdown dict with the given completeness percentages."""
    return {
        category: {"completeness_percentage": score, "actual_count": 1} for category, score in category_scores.items()
    }


class CategoryWeightTests(SimpleTestCase):
    """The published weights: Production 30 / Chemical 20 / Soil 18 / Pest 12 / Business 10 /
    Weather 5 / General 5. These are quoted in CLAUDE.md and shown to farmers as weight badges
    on the transparency page, so a silent drift here makes the UI lie."""

    def setUp(self):
        self.calc = TransparencyCalculator()

    def _score(self, bd):
        # history=None keeps the organic bypass and the certification bonus out of the way.
        return self.calc._calculate_completeness_score(bd, history=None)

    def test_all_categories_complete_scores_100(self):
        full = breakdown(production=100, chemical=100, soil=100, pest=100, weather=100, business=100, general=100)
        self.assertEqual(self._score(full), 100)

    def test_all_categories_empty_scores_0(self):
        empty = breakdown(production=0, chemical=0, soil=0, pest=0, weather=0, business=0, general=0)
        self.assertEqual(self._score(empty), 0)

    def test_each_category_carries_its_documented_weight(self):
        """One category at 100 and the rest at 0 must score that category's weight."""
        expected_weights = {
            "production": 30,
            "chemical": 20,
            "soil": 18,
            "pest": 12,
            "business": 10,
            "weather": 5,
            "general": 5,
        }
        for category, weight in expected_weights.items():
            with self.subTest(category=category):
                scores = {c: 0 for c in expected_weights}
                scores[category] = 100
                self.assertEqual(self._score(breakdown(**scores)), weight)

    def test_weights_sum_to_100(self):
        """Guards against a reweighting that quietly makes a perfect season score 97."""
        self.assertEqual(
            sum([30, 20, 18, 12, 10, 5, 5]),
            100,
            "documented category weights must total 100",
        )

    def test_absent_categories_are_excluded_not_counted_as_zero(self):
        """Only categories PRESENT in the breakdown contribute; the divisor is their combined
        weight. A production with production+chemical fully documented is at 100, not at 50."""
        partial = breakdown(production=100, chemical=100)
        self.assertEqual(self._score(partial), 100)


class PhotoPenaltyTierTests(SimpleTestCase):
    """Three tiers: ESSENTIAL events can lose up to 50% of their category credit, RECOMMENDED up
    to 25%, everything else nothing. The tier membership decides how hard a missing photo bites,
    so the sets are pinned by content, not just by size."""

    def setUp(self):
        self.calc = TransparencyCalculator()

    def test_essential_and_recommended_tiers_do_not_overlap(self):
        overlap = self.calc.PHOTO_TIER_ESSENTIAL & self.calc.PHOTO_TIER_RECOMMENDED
        self.assertEqual(overlap, set(), f"an event type cannot be in two photo tiers: {overlap}")

    def test_essential_tier_contains_the_high_stakes_records(self):
        """Planting, harvest and every spray class — the records an inspector reaches for."""
        for code in ("PL", "HA", "FE", "PE", "FU", "HE"):
            self.assertIn(code, self.calc.PHOTO_TIER_ESSENTIAL)

    def test_essential_penalty_is_at_most_50_percent(self):
        """`0.5 + 0.5 * verified_rate`: no photos halves the credit, never worse."""
        self.assertAlmostEqual(0.5 + 0.5 * 0.0, 0.5)
        self.assertAlmostEqual(0.5 + 0.5 * 1.0, 1.0)

    def test_recommended_penalty_is_at_most_25_percent(self):
        """`0.75 + 0.25 * verified_rate`."""
        self.assertAlmostEqual(0.75 + 0.25 * 0.0, 0.75)
        self.assertAlmostEqual(0.75 + 0.25 * 1.0, 1.0)


class AntiGamingTests(SimpleTestCase):
    """The two rules that stop a near-empty production from looking documented."""

    def setUp(self):
        self.calc = TransparencyCalculator()

    def test_thresholds_are_3_events_and_a_30_percent_cap(self):
        self.assertEqual(self.calc.MINIMUM_EVENTS_THRESHOLD, 3)
        self.assertEqual(self.calc.MINIMUM_EVENTS_SCORE_CAP, 30)

    @patch.object(TransparencyCalculator, "_get_farming_approach", return_value="organic")
    @patch.object(TransparencyCalculator, "_count_all_events", return_value=0)
    @patch.object(TransparencyCalculator, "_get_expected_event_count", return_value=13)
    def test_zero_events_scores_zero_and_short_circuits(self, _expected, _actual, _approach):
        """The guard exists so the organic bypass cannot award chemical credit — and thus a
        non-zero weighted score — to a production with nothing logged at all."""
        result = self.calc.calculate_transparency_score(history=object())

        self.assertEqual(result["transparency_percentage"], 0)
        self.assertEqual(result["completeness_score"], 0)
        self.assertEqual(result["actual_event_count"], 0)
        self.assertEqual(result["category_breakdown"], {})

    @patch.object(TransparencyCalculator, "_generate_consumer_summary", return_value="")
    @patch.object(TransparencyCalculator, "_generate_transparency_message", return_value="")
    @patch.object(TransparencyCalculator, "_get_farming_approach", return_value="organic")
    @patch.object(TransparencyCalculator, "_get_consumer_friendly_categories", return_value=[])
    @patch.object(TransparencyCalculator, "_calculate_completeness_score", return_value=95)
    @patch.object(TransparencyCalculator, "_analyze_category_completeness", return_value={})
    @patch.object(TransparencyCalculator, "_count_all_events", return_value=2)
    @patch.object(TransparencyCalculator, "_get_expected_event_count", return_value=13)
    def test_fewer_than_three_events_is_capped_at_30(self, *_mocks):
        """Two events that would otherwise weight out to 95 must report 30."""
        result = self.calc.calculate_transparency_score(history=object())
        self.assertEqual(result["transparency_percentage"], 30)

    @patch.object(TransparencyCalculator, "_generate_consumer_summary", return_value="")
    @patch.object(TransparencyCalculator, "_generate_transparency_message", return_value="")
    @patch.object(TransparencyCalculator, "_get_farming_approach", return_value="organic")
    @patch.object(TransparencyCalculator, "_get_consumer_friendly_categories", return_value=[])
    @patch.object(TransparencyCalculator, "_calculate_completeness_score", return_value=95)
    @patch.object(TransparencyCalculator, "_analyze_category_completeness", return_value={})
    @patch.object(TransparencyCalculator, "_count_all_events", return_value=3)
    @patch.object(TransparencyCalculator, "_get_expected_event_count", return_value=13)
    def test_exactly_three_events_is_not_capped(self, *_mocks):
        """The cap is `< 3`, so the third event lifts it. Pins the boundary."""
        result = self.calc.calculate_transparency_score(history=object())
        self.assertEqual(result["transparency_percentage"], 95)


class ReturnedShapeTests(SimpleTestCase):
    """`transparency_percentage` is the WEIGHTED completeness score, not the raw event ratio.
    The raw ratio is reported separately as `event_coverage_percentage`. Conflating them is how
    a farm with 20 of 10 expected events would read as 200% documented."""

    def setUp(self):
        self.calc = TransparencyCalculator()

    @patch.object(TransparencyCalculator, "_generate_consumer_summary", return_value="")
    @patch.object(TransparencyCalculator, "_generate_transparency_message", return_value="")
    @patch.object(TransparencyCalculator, "_get_farming_approach", return_value="conventional")
    @patch.object(TransparencyCalculator, "_get_consumer_friendly_categories", return_value=[])
    @patch.object(TransparencyCalculator, "_calculate_completeness_score", return_value=64)
    @patch.object(TransparencyCalculator, "_analyze_category_completeness", return_value={})
    @patch.object(TransparencyCalculator, "_count_all_events", return_value=20)
    @patch.object(TransparencyCalculator, "_get_expected_event_count", return_value=10)
    def test_percentage_is_weighted_score_and_coverage_is_capped_at_100(self, *_mocks):
        result = self.calc.calculate_transparency_score(history=object())

        self.assertEqual(result["transparency_percentage"], 64)
        self.assertEqual(result["event_coverage_percentage"], 100.0)
        self.assertEqual(result["actual_event_count"], 20)
        self.assertEqual(result["expected_event_count"], 10)
