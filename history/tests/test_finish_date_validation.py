"""
finish_date < start_date must be rejected everywhere the pair can be written.

Found 2026-08-10: the operation dossier printed a production window
"2026-08-09 – 2026-08-08" because a QA production was saved with its finish
before its start — nothing validated the pair. Two write paths exist:

1. HistoryWriteSerializer (PATCH /productions/<id>/, the edit-production form),
   where a partial update may send only one of the two dates.
2. ParcelViewSet._validate_finalization_fields (POST .../finish_production/),
   which bypasses serializer validation entirely.
"""

from datetime import datetime
from datetime import timezone as dt_timezone

from django.test import TestCase

from history.models import Production
from history.serializers import HistoryWriteSerializer
from product.views import ParcelViewSet


def _dt(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=dt_timezone.utc)


class HistoryWriteSerializerFinishDateTests(TestCase):
    def _history(self, **kwargs):
        return Production(**kwargs)

    def test_patch_finish_before_instance_start_rejected(self):
        instance = self._history(start_date=_dt(2026, 8, 9))
        ser = HistoryWriteSerializer(instance, data={"finish_date": "2026-08-08T12:00:00Z"}, partial=True)
        self.assertFalse(ser.is_valid())
        self.assertIn("finish_date", ser.errors)
        self.assertIn("2026-08-09", str(ser.errors["finish_date"][0]))

    def test_patch_start_after_instance_finish_rejected(self):
        # The inverse edit — moving start past an existing finish — is the
        # same corrupt window and must fail on the same rule.
        instance = self._history(start_date=_dt(2026, 8, 1), finish_date=_dt(2026, 8, 8))
        ser = HistoryWriteSerializer(instance, data={"start_date": "2026-08-20T12:00:00Z"}, partial=True)
        self.assertFalse(ser.is_valid())
        self.assertIn("finish_date", ser.errors)

    def test_same_day_finish_allowed(self):
        instance = self._history(start_date=_dt(2026, 8, 9))
        ser = HistoryWriteSerializer(instance, data={"finish_date": "2026-08-09T18:00:00Z"}, partial=True)
        self.assertTrue(ser.is_valid(), ser.errors)

    def test_normal_window_allowed(self):
        instance = self._history(start_date=_dt(2026, 8, 1))
        ser = HistoryWriteSerializer(instance, data={"finish_date": "2026-08-08T12:00:00Z"}, partial=True)
        self.assertTrue(ser.is_valid(), ser.errors)


class FinalizationFinishDateTests(TestCase):
    _BASE = {"production_amount": "100"}

    def _errors(self, finish_raw, start):
        view = ParcelViewSet()
        current = Production(start_date=start)
        data = dict(self._BASE, finish_date=finish_raw)
        return view._validate_finalization_fields(data, current_history=current)

    def test_finish_before_start_rejected(self):
        errors = self._errors("2026-08-08", start=_dt(2026, 8, 9))
        self.assertIsNotNone(errors)
        self.assertIn("finish_date", errors)
        self.assertIn("2026-08-09", errors["finish_date"][0])

    def test_same_day_finish_allowed(self):
        errors = self._errors("2026-08-09", start=_dt(2026, 8, 9))
        self.assertTrue(not errors or "finish_date" not in errors, errors)

    def test_no_current_history_skips_check(self):
        view = ParcelViewSet()
        data = dict(self._BASE, finish_date="2026-08-08")
        errors = view._validate_finalization_fields(data, current_history=None)
        self.assertTrue(not errors or "finish_date" not in errors, errors)
