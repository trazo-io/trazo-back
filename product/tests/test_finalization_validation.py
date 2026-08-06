"""
Finalization guard for POST .../parcels/{id}/finish_history/ (2026-07-31).

`History.finish()` assigns request values straight onto the model and saves, bypassing
serializer validation — so anything the database rejects surfaced as a 500 DataError at
the exact moment a grower publishes their season. `_validate_finalization_fields`
answers with field errors instead.

These tests pin the edge cases found while reviewing that validator:
  - it must not be STRICTER than History.finish(), which accepts a date-only string
  - a future finish date must be refused (a season that has not ended can't be final)
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from product.views import ParcelViewSet


class FinalizationValidationTests(TestCase):
    def setUp(self):
        self.validate = ParcelViewSet()._validate_finalization_fields
        self.valid = {
            "production_amount": "89000",
            "finish_date": (timezone.now() - timedelta(days=1)).isoformat(),
            "lot_id": "WHIT-B1-2026-001",
            "production_unit": "lb",
            "quality_grade": "premium",
            "harvest_method": "mechanical",
        }

    def test_valid_payload_passes(self):
        self.assertIsNone(self.validate(self.valid))

    def test_over_length_harvest_method_is_a_field_error_not_a_crash(self):
        """The original 500: harvest_method is max_length=20."""
        payload = {**self.valid, "harvest_method": "mechanical shake & sweep"}
        errors = self.validate(payload)
        self.assertIn("harvest_method", errors)
        self.assertIn("at most 20 characters", errors["harvest_method"][0])

    def test_invalid_choice_is_reported_with_the_valid_options(self):
        payload = {**self.valid, "quality_grade": "US No. 1"}
        errors = self.validate(payload)
        self.assertIn("quality_grade", errors)
        self.assertIn("premium", errors["quality_grade"][0])

    def test_non_numeric_production_amount(self):
        errors = self.validate({**self.valid, "production_amount": "lots"})
        self.assertEqual(errors["production_amount"], ["Enter a number."])

    def test_required_fields(self):
        errors = self.validate({})
        self.assertIn("production_amount", errors)
        self.assertIn("finish_date", errors)

    def test_future_finish_date_is_refused(self):
        payload = {**self.valid, "finish_date": (timezone.now() + timedelta(days=30)).isoformat()}
        errors = self.validate(payload)
        self.assertIn("finish_date", errors)
        self.assertIn("future", errors["finish_date"][0])

    def test_date_only_string_is_accepted(self):
        """
        History.finish() parses with datetime.fromisoformat(), which takes "2026-07-30".
        Validating with parse_datetime() alone rejected input the model would have
        stored — a validator stricter than the thing it guards.
        """
        yesterday = (timezone.now() - timedelta(days=1)).date().isoformat()
        self.assertIsNone(self.validate({**self.valid, "finish_date": yesterday}))

    def test_todays_date_only_is_not_treated_as_future(self):
        """A same-day finish is normal; it must not trip the future-date guard."""
        today = timezone.localtime(timezone.now()).date().isoformat()
        errors = self.validate({**self.valid, "finish_date": today})
        self.assertIsNone(errors, f"same-day finish rejected: {errors}")

    def test_unparseable_finish_date(self):
        errors = self.validate({**self.valid, "finish_date": "not-a-date"})
        self.assertIn("finish_date", errors)

    def test_blank_optional_fields_are_skipped(self):
        payload = {**self.valid, "quality_grade": "", "harvest_method": None}
        self.assertIsNone(self.validate(payload))
