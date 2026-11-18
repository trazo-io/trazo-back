"""The retired SoilManagementEvent columns (history/retired_columns.py), step 1 of 3.

Step 1 stops every reader and writer and clears the values through a logged data operation. These
tests hold: a correction cannot write a retired column back, the clear command (dry run, apply,
check, restore, and its refusal to write any other column), and the census counting held values
and refusing a drop until they are cleared.
"""

import json
import os
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from common.models import DataOperationLog
from common.services import census
from company.models import Company, Establishment
from history.amendments import AmendmentError, amendable_fields, apply_amendment
from history.constants import SOIL_MANAGEMENT_EVENT_TYPE
from history.models import EventAmendment, Production, SoilManagementEvent
from history.retired_columns import RETIRED_SOIL_EVENT_COLUMNS
from product.models import Parcel

LABEL = "history.SoilManagementEvent"
OPERATION = "clear_retired_soil_columns"


class _FarmMixin:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(email="retire-soil@example.com", password="pw-for-tests")
        company = Company.objects.create(name="Retire Soil Co")
        establishment = Establishment.objects.create(name="Retire Soil Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=establishment, area=1)
        self.season = Production.objects.create(parcel=parcel, name="2026", start_date=timezone.now())
        self.tmp = tempfile.mkdtemp()

    def _event(self, **values):
        return SoilManagementEvent.objects.create(
            history=self.season, type="CC", date=timezone.now(), description="Ryegrass", **values
        )

    def _run(self, name, *args):
        path = os.path.join(self.tmp, name)
        call_command(OPERATION, "--report", path, *args, stdout=open(os.devnull, "w"))
        with open(path) as handle:
            return json.load(handle)


class TheListTests(TestCase):
    def test_each_listed_column_is_a_nullable_field_today(self):
        """Step 1 keeps the fields in the model: old containers still name them."""
        fields = {f.name: f for f in SoilManagementEvent._meta.get_fields()}
        for column, empty in RETIRED_SOIL_EVENT_COLUMNS.items():
            self.assertIsNone(empty, column)
            self.assertTrue(fields[column].null, column)


class NoCorrectionWritesItBackTests(_FarmMixin, TestCase):
    def test_a_retired_column_is_not_offered_for_correction(self):
        names = {f.name for f in amendable_fields(SoilManagementEvent)}
        self.assertIn("soil_ph", names)  # the list was read
        self.assertEqual(names & set(RETIRED_SOIL_EVENT_COLUMNS), set())

    def test_a_correction_naming_it_is_refused(self):
        event = self._event()
        with self.assertRaisesMessage(AmendmentError, "is not a field that can be corrected"):
            apply_amendment(
                event=event,
                event_type=SOIL_MANAGEMENT_EVENT_TYPE,
                field_name="carbon_sequestration_potential",
                new_value="50",
                reason="typo",
                user=self.user,
            )
        event.refresh_from_db()
        self.assertIsNone(event.carbon_sequestration_potential)
        self.assertFalse(EventAmendment.objects.exists())


class ClearCommandTests(_FarmMixin, TestCase):
    def test_dry_run_apply_check_and_restore(self):
        held = self._event(carbon_sequestration_potential=Decimal("1.2"))
        clean = self._event()

        dry = self._run("dry.json")
        self.assertEqual([c["pk"] for c in dry["changes"]], [held.pk])
        held.refresh_from_db()
        self.assertEqual(held.carbon_sequestration_potential, Decimal("1.2"))  # the dry run wrote nothing
        self.assertFalse(DataOperationLog.objects.filter(operation=OPERATION).exists())

        count = SoilManagementEvent.objects.count()
        self._run("apply.json", "--apply")
        held.refresh_from_db()
        self.assertIsNone(held.carbon_sequestration_potential)
        self.assertEqual((held.description, held.type), ("Ryegrass", "CC"))  # only the retired column
        self.assertEqual(SoilManagementEvent.objects.count(), count)
        self.assertEqual(self._run("check.json")["changes"], [])

        log = DataOperationLog.objects.get(operation=OPERATION, action=DataOperationLog.ACTION_APPLY)
        call_command(OPERATION, "--restore", f"log:{log.pk}", stdout=open(os.devnull, "w"))
        held.refresh_from_db()
        self.assertEqual(held.carbon_sequestration_potential, Decimal("1.2"))
        clean.refresh_from_db()
        self.assertIsNone(clean.carbon_sequestration_potential)

    def test_restore_refuses_a_column_that_is_not_retired(self):
        from history.management.commands.clear_retired_soil_columns import write

        event = self._event()
        with self.assertRaises(CommandError):
            write(LABEL, event.pk, {"description": "rewritten"})
        with self.assertRaises(CommandError):
            write("history.ChemicalEvent", event.pk, {"carbon_sequestration_potential": None})
        event.refresh_from_db()
        self.assertEqual(event.description, "Ryegrass")


def _drop(snapshot, label, columns):
    """The census `snapshot` as it would read after `columns` left `label`'s table."""
    after = json.loads(json.dumps(snapshot))
    table = after["tables"][label]
    n = census.CELL_HASH_CHARS
    keep = [i for i, c in enumerate(table["columns"]) if c not in columns]
    for key, row in table["rows"].items():
        digest, cells = row.split(":", 1)
        table["rows"][key] = digest + ":" + "".join(cells[i * n : (i + 1) * n] for i in keep)
    table["columns"] = [table["columns"][i] for i in keep]
    after["domain"]["retiring_columns"][label] = {
        c: v for c, v in after["domain"]["retiring_columns"][label].items() if c not in columns
    }
    return after


class CensusTests(_FarmMixin, TransactionTestCase):
    """`TransactionTestCase`: the census opens its own read-only snapshot transaction."""

    def test_the_census_counts_rows_holding_a_value(self):
        self._event(carbon_sequestration_potential=Decimal("1.2"))
        self._event()
        facts = census._retiring_column_facts()[LABEL]
        self.assertEqual(facts, {"carbon_sequestration_potential": 1})

    def test_a_drop_is_a_loss_until_the_values_are_cleared(self):
        self._event(carbon_sequestration_potential=Decimal("1.2"))
        dropped = sorted(RETIRED_SOIL_EVENT_COLUMNS)

        held = census.take_census(label="held")
        result = census.compare(held, _drop(held, LABEL, dropped))
        self.assertFalse(result["ok"])
        [loss] = [x for x in result["losses"] if "still held a value" in x]
        self.assertIn("'carbon_sequestration_potential': 1", loss)

        self._run("apply.json", "--apply")
        cleared = census.take_census(label="cleared")
        result = census.compare(cleared, _drop(cleared, LABEL, dropped))
        self.assertTrue(result["ok"], result["losses"])
        self.assertTrue(any("retired columns dropped" in note for note in result["notes"]))
