"""The backfill that stores "not answered" for the old switch's False (OV-RK-C15, 2026-11-26).

WHY. Before history 0268 an unanswered "certifier notified?" was saved as False, so every row
from that time is unknown. `null_unanswered_certifier_notified` rewrites False with no
notification date to None. It must touch nothing else, save nothing on a dry run, change nothing
on a second run, and put every False back on restore, from the file or from the log row (a
production container's disk does not survive a deploy).
"""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from common.models import DataOperationLog
from company.models import Company, Establishment
from history.models import GeneralEvent, Production
from product.models import Parcel


class NullUnansweredCertifierNotified(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Backfill Farm")
        establishment = Establishment.objects.create(name="Backfill", company=company, state="WA")
        parcel = Parcel.objects.create(name="North", establishment=establishment, area=2.0)
        self.history = Production.objects.create(
            name="Backfill season", start_date=timezone.now() - timedelta(days=30), parcel=parcel
        )

    def _event(self, **fields):
        return GeneralEvent.objects.create(history=self.history, date=timezone.now(), description="x", **fields)

    def _values(self, *events):
        return [GeneralEvent.objects.get(pk=e.pk).certifier_notified for e in events]

    def test_only_an_undated_false_becomes_not_answered(self):
        old_incident = self._event(is_contamination_incident=True, certifier_notified=False)
        old_note = self._event(is_contamination_incident=False, certifier_notified=False)
        dated_false = self._event(
            is_contamination_incident=True, certifier_notified=False, certifier_notification_date=date(2026, 5, 2)
        )
        notified = self._event(is_contamination_incident=True, certifier_notified=True)
        unanswered = self._event(is_contamination_incident=True)
        untouched = (dated_false, notified, unanswered)
        before_untouched = self._values(*untouched)

        with tempfile.TemporaryDirectory() as d:
            dry = Path(d) / "dry.json"
            call_command("null_unanswered_certifier_notified", report=str(dry))
            self.assertEqual(self._values(old_incident, old_note), [False, False], "a dry run saves nothing")
            report = json.loads(dry.read_text())
            changed = {c["pk"]: c for c in report["changes"]}
            self.assertEqual(set(changed), {old_incident.pk, old_note.pk})
            self.assertTrue(changed[old_incident.pk]["before"]["_incident"])
            self.assertEqual(changed[old_incident.pk]["before"]["_establishment"], "Backfill")

            applied = Path(d) / "apply.json"
            call_command("null_unanswered_certifier_notified", report=str(applied), apply=True, run_by="test")
            self.assertEqual(self._values(old_incident, old_note), [None, None])
            self.assertEqual(self._values(*untouched), before_untouched, "rows with an answer are not touched")

            again = Path(d) / "again.json"
            call_command("null_unanswered_certifier_notified", report=str(again))
            self.assertEqual(json.loads(again.read_text())["changes"], [], "a second run changes nothing")

            call_command("null_unanswered_certifier_notified", restore=str(applied), run_by="test")
            self.assertEqual(self._values(old_incident, old_note), [False, False])

    def test_restore_from_the_log_row_when_the_file_is_gone(self):
        old_incident = self._event(is_contamination_incident=True, certifier_notified=False)
        with tempfile.TemporaryDirectory() as d:
            call_command(
                "null_unanswered_certifier_notified", report=str(Path(d) / "apply.json"), apply=True, run_by="test"
            )
        self.assertIsNone(self._values(old_incident)[0])
        log = DataOperationLog.objects.get(
            operation="null_unanswered_certifier_notified", action=DataOperationLog.ACTION_APPLY
        )
        call_command("null_unanswered_certifier_notified", restore=f"log:{log.pk}", run_by="test")
        self.assertIs(self._values(old_incident)[0], False)
