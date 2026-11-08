"""TransparencyCalculator returns FACTS only (2026-11-08).

Until 2026-11-08 this file pinned the arithmetic of a 0-100 transparency score: category weights,
three-tier photo multipliers, a zero-event guard and a fewer-than-three-events cap. The score is
retired as a concept (`.claude/rules/transparency-first.md`); the column went in history 0237/0238,
and on 2026-11-08 the calculator stopped computing it at all. What it returns now is what the
consumer QR page shows: how many events a production logged per category, how many carry a photo,
and the farming approach.

DB-free: the counting helpers are patched, so no Establishment/Parcel/History chain is needed.
"""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from history.services.transparency_calculator import TransparencyCalculator

GRADE_KEYS = {
    "transparency_percentage",
    "completeness_score",
    "event_coverage_percentage",
    "message",
    "consumer_summary",
    "consumer_friendly_categories",
    "expected_event_count",
}


class FactsOnlyTests(SimpleTestCase):
    def setUp(self):
        self.calc = TransparencyCalculator()
        self.history = SimpleNamespace(id=7)

    @patch.object(TransparencyCalculator, "_ensure_prefetched", return_value=None)
    @patch.object(TransparencyCalculator, "_get_farming_approach", return_value="organic")
    @patch.object(TransparencyCalculator, "_count_all_events", return_value=4)
    @patch.object(
        TransparencyCalculator,
        "_category_counts",
        return_value={"production": {"actual_count": 4, "photo_verified_count": 1}},
    )
    def test_it_returns_counts_and_the_approach_only(self, *_):
        facts = self.calc.calculate_transparency_score(self.history)
        self.assertEqual(
            facts,
            {
                "actual_event_count": 4,
                "farming_approach": "organic",
                "category_breakdown": {"production": {"actual_count": 4, "photo_verified_count": 1}},
            },
        )
        self.assertEqual(set(facts) & GRADE_KEYS, set())

    @patch.object(TransparencyCalculator, "_ensure_prefetched", side_effect=RuntimeError("boom"))
    def test_an_error_returns_the_same_keys_so_the_view_can_index_them(self, *_):
        """The error path used to return only a percentage and a message, and the QR view reads
        `actual_event_count` by key."""
        facts = self.calc.calculate_transparency_score(self.history)
        for key in ("actual_event_count", "farming_approach", "category_breakdown"):
            self.assertIn(key, facts)
        self.assertEqual(facts["actual_event_count"], 0)
        self.assertEqual(set(facts) & GRADE_KEYS, set())

    def test_category_counts_carry_no_grade(self):
        events = {"ProductionEvent": [object(), object()], "ChemicalEvent": [object()]}
        with (
            patch.object(
                TransparencyCalculator,
                "_events_of",
                side_effect=lambda history, model: events.get(model.__name__, []),
            ),
            patch.object(TransparencyCalculator, "_has_photo_verification", return_value=True),
        ):
            breakdown = self.calc._category_counts(self.history)
        self.assertEqual(breakdown["production"], {"actual_count": 2, "photo_verified_count": 2})
        self.assertEqual(breakdown["chemical"], {"actual_count": 1, "photo_verified_count": 1})
        self.assertEqual(breakdown["weather"], {"actual_count": 0, "photo_verified_count": 0})
        for category in breakdown.values():
            self.assertEqual(set(category), {"actual_count", "photo_verified_count"})

    def test_the_grading_helpers_are_gone(self):
        for name in (
            "_calculate_completeness_score",
            "_get_transparency_level",
            "_get_category_status",
            "_generate_consumer_summary",
            "_generate_transparency_message",
            "_get_expected_event_count",
            "EXPECTED_EVENTS",
            "MINIMUM_EVENTS_SCORE_CAP",
        ):
            self.assertFalse(hasattr(TransparencyCalculator, name), name)
