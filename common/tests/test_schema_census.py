"""The schema census reads only, repeats exactly, and notices every loss a remodel could cause.

`TransactionTestCase`, not `TestCase`: the census opens its own transaction with
`SET TRANSACTION ... READ ONLY`, which must be the first statement of a real transaction. Inside
`TestCase`'s wrapping transaction it would be a savepoint, and Postgres would refuse it.
"""

import json
import tempfile
from io import StringIO
from unittest import mock

from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import InternalError, connection
from django.test import TransactionTestCase
from django.utils import timezone

from common.services import census as svc
from company.models import Company, Establishment
from history.models import ChemicalEvent, EventAmendment, GeneralEvent, History
from product.models import Parcel

SHARED_PK = 424_242


class SchemaCensusTests(TransactionTestCase):
    def setUp(self):
        company = Company.objects.create(name="Census Co")
        est = Establishment.objects.create(name="Census Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=est, area=1)
        self.history = History.objects.create(parcel=parcel, name="2026 Season")
        self.general = GeneralEvent.objects.create(
            pk=SHARED_PK, history=self.history, name="g", description="general", date=timezone.now(), index=1
        )
        self.chemical = ChemicalEvent.objects.create(
            pk=SHARED_PK,
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Fish Emulsion",
            description="chemical",
            date=timezone.now(),
            index=1,
        )

    # ---- read only, repeatable -----------------------------------------------------------------

    def test_two_censuses_of_the_same_data_are_identical(self):
        a, b = svc.take_census("a"), svc.take_census("b")
        self.assertEqual(a["tables"], b["tables"])
        self.assertEqual(a["domain"], b["domain"])
        self.assertTrue(svc.compare(a, b)["ok"])

    def test_the_census_transaction_refuses_writes(self):
        """A helper that tried to write would fail loudly instead of changing what it measures."""

        def writes(*args, **kwargs):
            with connection.cursor() as cursor:
                cursor.execute("UPDATE history_generalevent SET description = 'x'")

        with mock.patch.object(svc, "_event_facts", side_effect=writes), self.assertRaises(InternalError):
            svc.take_census()
        self.general.refresh_from_db()
        self.assertEqual(self.general.description, "general")

    def test_every_concrete_table_is_covered_including_audit_and_m2m(self):
        census = svc.take_census()
        for label in (
            "history.History",
            "history.GeneralEvent",
            "history.ChemicalEvent",
            "history.EquipmentEvent",
            "contenttypes.ContentType",
            "auditlog.LogEntry",
            "history.SalesRecord_harvest_events",
        ):
            self.assertIn(label, census["tables"])
        self.assertEqual(census["tables"]["history.ChemicalEvent"]["count"], 1)

    # ---- domain facts ---------------------------------------------------------------------------

    def test_event_id_collisions_and_index_ties_are_recorded(self):
        events = svc.take_census()["domain"]["events"]
        self.assertEqual(events["id_collisions"]["count"], 1)
        self.assertIn(SHARED_PK, events["id_collisions"]["sample"])
        self.assertEqual(events["seasons_with_index_ties"]["ids"], [self.history.pk])

    def test_a_loose_pair_pointing_at_nothing_is_an_orphan(self):
        EventAmendment.objects.create(history=self.history, event_type=2, event_id=999_999, field_name="x", reason="r")
        EventAmendment.objects.create(
            history=self.history, event_type=2, event_id=SHARED_PK, field_name="x", reason="r"
        )
        pairs = svc.take_census()["domain"]["loose_pairs"]["history.EventAmendment"]
        self.assertEqual(pairs["with_target"], 2)
        self.assertEqual(pairs["orphans"]["count"], 1)

    def test_a_sealed_season_records_both_layers_and_its_preimage_order(self):
        current, count = self.history.compute_finalization_hash()
        History.objects.filter(pk=self.history.pk).update(
            extra_data={"finalization_hash": current, "finalization_event_count": count}
        )
        seal = svc.take_census()["domain"]["seals"]["seasons"][str(self.history.pk)]
        self.assertEqual(seal["layer1"], "intact")
        self.assertEqual(seal["layer2"], "not_submitted")
        self.assertEqual(sorted(seal["v1_preimage_order"]), [["ChemicalEvent", SHARED_PK], ["GeneralEvent", SHARED_PK]])

    # ---- compare --------------------------------------------------------------------------------

    def test_a_deleted_row_is_a_loss(self):
        before = svc.take_census()
        GeneralEvent.objects.filter(pk=SHARED_PK).delete()
        result = svc.compare(before, svc.take_census())
        self.assertFalse(result["ok"])
        self.assertTrue(any("history.GeneralEvent: 1 rows missing" in loss for loss in result["losses"]))

    def test_a_changed_row_is_listed_with_its_column_and_a_new_row_is_counted(self):
        before = svc.take_census()
        GeneralEvent.objects.filter(pk=SHARED_PK).update(description="edited")
        GeneralEvent.objects.create(history=self.history, name="n", description="new", date=timezone.now())
        result = svc.compare(before, svc.take_census())
        self.assertTrue(result["ok"], result["losses"])
        self.assertEqual(result["changed"]["history.GeneralEvent"]["columns"], ["description"])
        self.assertEqual(result["added"]["history.GeneralEvent"], 1)

    def test_a_seal_that_stops_verifying_is_a_loss(self):
        current, count = self.history.compute_finalization_hash()
        History.objects.filter(pk=self.history.pk).update(
            extra_data={"finalization_hash": current, "finalization_event_count": count}
        )
        before = svc.take_census()
        GeneralEvent.objects.filter(pk=SHARED_PK).update(description="edited after sealing")
        result = svc.compare(before, svc.take_census())
        self.assertFalse(result["ok"])
        self.assertTrue(any("layer1 verified before" in loss for loss in result["losses"]))

    def test_a_declared_rename_is_not_a_missing_table(self):
        before = svc.take_census()
        after = svc.take_census()
        after["tables"]["history.Production"] = after["tables"].pop("history.History")
        # RenameModel also renames the ContentType row (Django injects RenameContentType).
        counts = after["domain"]["audit_trail"]["auditlog_entries_by_content_type"]
        if "history.history" in counts:
            counts["history.production"] = counts.pop("history.history")
        self.assertFalse(svc.compare(before, after)["ok"])
        self.assertTrue(svc.compare(before, after, renames={"history.History": "history.Production"})["ok"])

    def test_canonical_values_keep_null_distinct_from_empty(self):
        self.assertNotEqual(svc._sha(svc.canonical(None)), svc._sha(svc.canonical("")))

    # ---- command --------------------------------------------------------------------------------

    def test_command_stores_privately_and_compare_fails_on_a_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = FileSystemStorage(location=tmp)
            target = "common.management.commands.schema_census.private_records_storage"
            with mock.patch(target, return_value=storage):
                out = StringIO()
                call_command("schema_census", label="before", store=True, stdout=out)
                stored = [line for line in out.getvalue().splitlines() if line.startswith("stored storage:")]
                self.assertEqual(len(stored), 1)
                ref = stored[0].split(" ", 1)[1]
                self.assertTrue(ref.startswith("storage:ops/census/"))
                saved = json.loads(storage.open(ref[len("storage:") :]).read())
                self.assertEqual(saved["label"], "before")

                call_command("schema_census", compare=ref, stdout=StringIO())  # nothing lost

                GeneralEvent.objects.filter(pk=SHARED_PK).delete()
                with self.assertRaisesMessage(CommandError, "census lost data"):
                    call_command("schema_census", compare=ref, stdout=StringIO())

    def test_a_sequence_behind_its_table_is_reported_and_one_that_falls_behind_is_a_loss(self):
        """Inserting with an explicit pk (setUp does) leaves the sequence behind: the next plain
        insert would collide. Already behind before: reported, not blamed on the migration."""
        before = svc.take_census()
        self.assertIn("history.GeneralEvent", svc.summary(before)["sequences_behind"])
        self.assertTrue(svc.compare(before, svc.take_census())["ok"])

        healthy = svc.take_census()
        healthy["sequences"]["history.GeneralEvent"]["ok"] = True
        result = svc.compare(healthy, svc.take_census())
        self.assertFalse(result["ok"])
        self.assertTrue(any("fell behind" in loss for loss in result["losses"]))

    def test_command_refuses_a_database_with_unapplied_migrations(self):
        """Against a database behind the code it would fail halfway on the first missing table."""
        fake_migration = mock.Mock(app_label="history", name="0999_not_applied")
        fake_migration.name = "0999_not_applied"
        target = "common.management.commands.schema_census.MigrationExecutor.migration_plan"
        with mock.patch(target, return_value=[(fake_migration, False)]):
            with self.assertRaisesMessage(CommandError, "1 migrations are not applied"):
                call_command("schema_census", stdout=StringIO())

    def test_a_declared_rename_carries_audit_entries_and_orphan_checks(self):
        """Review of back #289: content types are lower case, renames are model labels."""
        before = svc.take_census()
        before["domain"]["audit_trail"]["auditlog_entries_by_content_type"] = {"history.history": 3}
        before["domain"]["loose_pairs"]["history.EventAmendment"]["orphans"]["count"] = 0
        after = svc.take_census()
        after["tables"]["history.Production"] = after["tables"].pop("history.History")
        after["domain"]["audit_trail"]["auditlog_entries_by_content_type"] = {"history.production": 3}
        pairs = after["domain"]["loose_pairs"].pop("history.EventAmendment")
        pairs["orphans"]["count"] = 2
        after["domain"]["loose_pairs"]["history.EventAmendmentRenamed"] = pairs
        renames = {"history.History": "history.Production", "history.EventAmendment": "history.EventAmendmentRenamed"}

        result = svc.compare(before, after, renames=renames)
        self.assertFalse(any("auditlog entries" in loss for loss in result["losses"]), result["losses"])
        self.assertTrue(any("orphan pairs grew 0 -> 2" in loss for loss in result["losses"]), result["losses"])

    def test_a_database_error_in_one_seal_check_is_recorded_and_the_census_finishes(self):
        """Review of back #289: without a savepoint the error aborts the whole transaction."""
        current, count = self.history.compute_finalization_hash()
        History.objects.filter(pk=self.history.pk).update(
            extra_data={"finalization_hash": current, "finalization_event_count": count}
        )

        def broken(self_history):
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM table_that_does_not_exist")

        with mock.patch.object(History, "compute_finalization_hash", broken):
            census = svc.take_census()
        seal = census["domain"]["seals"]["seasons"][str(self.history.pk)]
        self.assertTrue(seal["layer1"].startswith("error:"), seal["layer1"])
        self.assertEqual(sorted(seal["v1_preimage_order"]), [["ChemicalEvent", SHARED_PK], ["GeneralEvent", SHARED_PK]])
