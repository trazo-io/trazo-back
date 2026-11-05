"""`diagnose_seals` names the cause of each finalization-hash mismatch, and only reads.

TransactionTestCase: the command opens its own `SET TRANSACTION ... READ ONLY` transaction, which
Postgres refuses inside TestCase's wrapping transaction.
"""

import json
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TransactionTestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.management.commands import diagnose_seals as cmd
from history.models import ChemicalEvent, GeneralEvent, History
from product.models import Parcel


class DiagnoseSealsTests(TransactionTestCase):
    def setUp(self):
        company = Company.objects.create(name="Seal Co")
        est = Establishment.objects.create(name="Seal Farm", company=company)
        self.parcel = Parcel.objects.create(name="North", establishment=est, area=1)

    def _season(self, name="2026"):
        history = History.objects.create(parcel=self.parcel, name=name)
        GeneralEvent.objects.create(history=history, name="g", description="general", date=timezone.now(), index=1)
        ChemicalEvent.objects.create(
            history=history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Fish",
            description="chemical",
            date=timezone.now(),
            index=2,
        )
        return history

    def _seal(self, history, stored=None, at=None):
        current, count = history.compute_finalization_hash()
        History.objects.filter(pk=history.pk).update(
            extra_data={
                "finalization_hash": stored or current,
                "finalization_event_count": count,
                "finalization_timestamp": (at or timezone.now()).isoformat(),
            }
        )
        history.refresh_from_db()

    def _run(self, history):
        out = StringIO()
        call_command("diagnose_seals", season=[history.pk], stdout=out)
        lines = out.getvalue().strip().splitlines()
        return json.loads(lines[0]), lines

    def test_the_replicated_preimage_is_the_models_own_hash(self):
        history = self._season()
        text = cmd._serialise(cmd._season_rows(history))
        self.assertIn(history.compute_finalization_hash()[0], (cmd._keccak(text), cmd._sha256(text)))

    def test_an_untouched_seal_is_intact(self):
        history = self._season()
        self._seal(history)
        report, _ = self._run(history)
        self.assertEqual(report["verdict"], "intact")
        self.assertEqual(report["company"], "Seal Co")
        self.assertEqual(report["farm"], "Seal Farm")

    def test_an_edit_to_a_hashed_field_after_sealing_is_named(self):
        history = self._season()
        self._seal(history)
        event = GeneralEvent.objects.get(history=history)
        event.description = "rewritten after the seal"
        event.save()  # a real save, so the audit log records the change
        report, _ = self._run(history)
        self.assertEqual(report["verdict"], "hashed_field_edited_after_seal")
        self.assertEqual(report["hashed_fields_changed_after_seal"], ["description"])

    def test_a_seal_older_than_its_events_is_a_copied_seal(self):
        """A seeder that carries extra_data across but creates new event rows."""
        history = self._season()
        self._seal(history, stored="0" * 64, at=timezone.now() - timedelta(days=30))
        report, _ = self._run(history)
        self.assertEqual(report["verdict"], "seal_predates_its_events")
        self.assertEqual(report["events_created_after_seal"], 2)

    def test_a_different_order_of_index_ties_is_found(self):
        history = self._season()
        ChemicalEvent.objects.filter(history=history).update(index=1)
        rows = cmd._season_rows(history)
        swapped = cmd._serialise([rows[1], rows[0]])
        stored = cmd._keccak(swapped) or cmd._sha256(swapped)
        if stored == history.compute_finalization_hash()[0]:
            self.skipTest("both tie orders hash the same")
        self._seal(history, stored=stored)
        report, _ = self._run(history)
        self.assertEqual(report["verdict"], "tie_order")
        self.assertEqual(report["tie_orders"], 2)

    def test_a_deleted_event_is_a_changed_count(self):
        history = self._season()
        self._seal(history)
        GeneralEvent.objects.filter(history=history).delete()
        report, _ = self._run(history)
        self.assertEqual(report["verdict"], "event_count_changed")
        self.assertEqual((report["stored_event_count"], report["current_event_count"]), (2, 1))

    def test_the_summary_line_counts_verdicts_and_prints_no_email(self):
        history = self._season()
        self._seal(history)
        _, lines = self._run(history)
        self.assertEqual(json.loads(lines[-1]), {"seasons": 1, "verdicts": {"intact": 1}})
        self.assertNotIn("@", "\n".join(lines))

    def test_an_event_deleted_after_the_seal_is_counted(self):
        """Review of back #291: the deleted row is not among the current events."""
        history = self._season()
        self._seal(history)
        GeneralEvent.objects.get(history=history).delete()
        report, _ = self._run(history)
        self.assertEqual(report["audit_after_seal"]["delete"], 1)

    def test_a_deletion_without_a_stored_count_is_still_named(self):
        history = self._season()
        self._seal(history)
        extra = dict(history.extra_data)
        extra.pop("finalization_event_count")
        History.objects.filter(pk=history.pk).update(extra_data=extra)
        GeneralEvent.objects.get(history=history).delete()
        report, _ = self._run(history)
        self.assertEqual(report["verdict"], "changed_after_seal")

    def test_a_partly_audited_season_with_a_later_event_is_a_count_change_not_a_copied_seal(self):
        """Review of back #291: events with no CREATE entry are no evidence of a copied seal."""
        from auditlog.models import LogEntry

        history = self._season()
        self._seal(history)
        LogEntry.objects.filter(action=LogEntry.Action.CREATE).delete()  # pre-auditlog rows
        GeneralEvent.objects.create(history=history, name="late", description="late", date=timezone.now(), index=3)
        report, _ = self._run(history)
        self.assertEqual(report["events_created_after_seal"], 1)
        self.assertEqual(report["verdict"], "event_count_changed")

    def test_a_wide_tie_sealed_in_pk_order_is_a_row_order_change(self):
        """Prod 2026-11: 22 events on one index (22! orders). The seal was taken in insertion order;
        the database now returns another. Too many permutations to try, so the likely seal-time
        orders are tried by name."""
        history = History.objects.create(parcel=self.parcel, name="wide tie")
        for i in range(9):
            GeneralEvent.objects.create(
                history=history, name=f"g{i}", description=f"d{i}", date=timezone.now(), index=0
            )
        rows = cmd._season_rows(history)
        in_pk_order = cmd._serialise(sorted(rows, key=lambda r: r["id"]))
        stored = cmd._keccak(in_pk_order) or cmd._sha256(in_pk_order)
        # Make the current database order differ from pk order, the way a later UPDATE does.
        newest_first = cmd._serialise(sorted(rows, key=lambda r: -r["id"]))
        self._seal(history, stored=stored)
        with mock.patch.object(cmd, "_season_rows", return_value=json.loads(newest_first)):
            report, _ = self._run(history)
        self.assertEqual(report["tie_orders"], 362880)  # 9!: beyond MAX_TIE_ORDERS
        self.assertIsNone(report["matches_a_tie_order"])
        self.assertEqual(report["matches_row_order"], "pk_ascending")
        self.assertEqual(report["verdict"], "row_order_changed")

    def test_a_mismatch_sealed_before_the_audit_log_existed_is_named_unaudited(self):
        """Production 2026-11: sealed 2026-03-01, event models registered with auditlog on
        2026-04-20. The season's own events have no CREATE entry (they predate the log); the
        coverage start comes from OTHER events' entries, dated after the seal."""
        from auditlog.models import LogEntry

        history = self._season()
        sealed_at = timezone.now() - timedelta(days=60)
        self._seal(history, stored="f" * 64, at=sealed_at)
        LogEntry.objects.all().delete()  # this season's events predate the log
        other = History.objects.create(parcel=self.parcel, name="later season")
        GeneralEvent.objects.create(history=other, name="later", description="later", date=timezone.now())
        coverage = sealed_at + timedelta(days=50)
        LogEntry.objects.update(timestamp=coverage)
        report, _ = self._run(history)
        self.assertEqual(report["audit_coverage_start"], str(coverage).replace("T", " "))
        self.assertTrue(report["sealed_before_audit_coverage"])
        self.assertEqual(report["verdict"], "changed_while_unaudited")

    def test_no_audit_entries_at_all_is_not_evidence_of_an_unaudited_window(self):
        """Review of back #296: zero entries (bulk-seeded rows) must stay `unexplained`."""
        from auditlog.models import LogEntry

        history = self._season()
        self._seal(history, stored="f" * 64, at=timezone.now() - timedelta(days=60))
        LogEntry.objects.all().delete()
        report, _ = self._run(history)
        self.assertIsNone(report["audit_coverage_start"])
        self.assertFalse(report["sealed_before_audit_coverage"])
        self.assertEqual(report["verdict"], "unexplained")

    def test_a_mismatch_inside_audit_coverage_stays_unexplained(self):
        from auditlog.models import LogEntry

        history = self._season()
        self._seal(history, stored="f" * 64, at=timezone.now() + timedelta(seconds=1))
        LogEntry.objects.filter(action=LogEntry.Action.CREATE).update(timestamp=timezone.now() - timedelta(days=1))
        report, _ = self._run(history)
        self.assertFalse(report["sealed_before_audit_coverage"])
        self.assertEqual(report["verdict"], "unexplained")
