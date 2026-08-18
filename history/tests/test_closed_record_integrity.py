"""A finished production is a closed record (2026-08-18).

Events on a finished production were hard-locked (423/403), but the lot header they
describe travelled through the ordinary PATCH with no guard at all. Measured before the
fix: `PATCH /histories/<id>/` rewrote lot_id, production_amount, quality_grade,
harvest_method and finish_date on a finished, published season and returned 200.

That is backwards. `lot_id` and `production_amount` are the traceability spine
7 CFR 205.103(b)(2) asks to be auditable "back to the last certified operation"; the
spray records underneath them were the part already protected.

`finish_date` mattered twice over: it was a working undocumented re-open (clearing it
released every event lock), and `retention_until` is computed only inside
History.finish(), so moving it desynchronised the 5-year floor.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company
from history.models import History
from history.serializers import HistoryWriteSerializer
from product.models import Establishment, Parcel


class ClosedRecordGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = Company.objects.create(name="Guard Co")
        est = Establishment.objects.create(name="Guard Farm", company=company)
        cls.parcel = Parcel.objects.create(name="Guard Parcel", establishment=est, area=1)

    def _history(self, finished):
        h = History.objects.create(
            parcel=self.parcel,
            name="Season",
            lot_id="LOT-ORIGINAL",
            production_amount=100,
            start_date=timezone.now() - timedelta(days=200),
        )
        if finished:
            h.finish_date = timezone.now() - timedelta(days=1)
            h.save()
        return h

    def _errors(self, history, payload):
        s = HistoryWriteSerializer(instance=history, data=payload, partial=True)
        return {} if s.is_valid() else s.errors

    # --- open productions stay fully editable -------------------------------

    def test_open_production_lot_header_is_editable(self):
        """The guard must not freeze a season that is still running."""
        errors = self._errors(self._history(finished=False), {"lot_id": "LOT-CORRECTED"})
        self.assertEqual(errors, {})

    def test_open_production_may_be_finished(self):
        errors = self._errors(self._history(finished=False), {"finish_date": timezone.now()})
        self.assertEqual(errors, {})

    # --- finished productions are frozen ------------------------------------

    def test_finished_lot_id_is_rejected(self):
        errors = self._errors(self._history(finished=True), {"lot_id": "LOT-REWRITTEN"})
        self.assertIn("lot_id", errors)

    def test_finished_production_amount_is_rejected(self):
        errors = self._errors(self._history(finished=True), {"production_amount": 99999})
        self.assertIn("production_amount", errors)

    def test_finished_quality_and_harvest_are_rejected(self):
        errors = self._errors(
            self._history(finished=True),
            {"quality_grade": "premium", "harvest_method": "mechanical"},
        )
        self.assertIn("quality_grade", errors)
        self.assertIn("harvest_method", errors)

    def test_finish_date_cannot_be_nulled_the_reopen_path(self):
        """PATCH {"finish_date": null} used to release every event lock at once."""
        errors = self._errors(self._history(finished=True), {"finish_date": None})
        self.assertIn("finish_date", errors)

    def test_finish_date_cannot_be_moved(self):
        """Moving it desynchronised retention_until, which finish() alone computes."""
        errors = self._errors(self._history(finished=True), {"finish_date": timezone.now() - timedelta(days=30)})
        self.assertIn("finish_date", errors)

    # --- a no-op resubmit must not be treated as a rewrite -------------------

    def test_resubmitting_identical_values_is_allowed(self):
        """Guard compares against the stored value, so an idempotent PATCH still works."""
        h = self._history(finished=True)
        errors = self._errors(h, {"lot_id": h.lot_id, "finish_date": h.finish_date})
        self.assertEqual(errors, {})

    def test_unrelated_field_still_editable_after_finish(self):
        """Freezing the harvest record must not freeze the whole row."""
        errors = self._errors(self._history(finished=True), {"name": "Renamed season"})
        self.assertEqual(errors, {})
