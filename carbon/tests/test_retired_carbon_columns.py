"""Retiring the dead CarbonEntry columns (carbon/retired_columns.py), step 1 of 2.

Nothing writes them, `clear_retired_carbon_columns` empties them with a restorable report, and the
census lets a later migration drop one only when no row held a value in it.
"""

import json
import os
import tempfile

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from carbon.models import CarbonEntry
from carbon.retired_columns import RETIRED_CARBON_ENTRY_COLUMNS
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from common.models import DataOperationLog
from common.services import census
from company.models import Company, Establishment
from history.models import History, PestManagementEvent
from product.models import Parcel

LEGACY_VALUES = {
    "external_verification_id": "EXT-PestManagementEvent-1",
    "verification_notes": "USDA verified fuel consumption data",
    "verification_report_url": "https://usda.gov/verify/1",
    "gps_coordinates": {"establishment": "North"},
    "confidence_level": "high",
    "improvement_potential": 1.5,
}


class _FarmMixin:
    def setUp(self):
        company = Company.objects.create(name="Retire Co")
        self.est = Establishment.objects.create(name="Retire Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=self.est, area=1)
        self.season = History.objects.create(parcel=parcel, name="2026", start_date=timezone.now())
        self.event = PestManagementEvent.objects.create(
            history=self.season, type="SC", description="scouting", date=timezone.now()
        )
        CarbonEntry.objects.all().delete()  # whatever the save receivers wrote
        self.dir = tempfile.mkdtemp()

    def _entry(self, **kw):
        values = dict(
            production=self.season,
            establishment=self.est,
            type="emission",
            amount=2,
            co2e_amount=2,
            year=timezone.now().year,
            description="Diesel",
        )
        values.update(kw)
        return CarbonEntry.objects.create(**values)

    def _run(self, name, *flags):
        path = os.path.join(self.dir, name)
        call_command("clear_retired_carbon_columns", "--report", path, *flags, stdout=open(os.devnull, "w"))
        with open(path) as handle:
            return json.load(handle)


class TheListTests(TestCase):
    def test_each_empty_value_is_the_fields_default(self):
        fields = {f.name: f for f in CarbonEntry._meta.concrete_fields}
        for column, empty in RETIRED_CARBON_ENTRY_COLUMNS.items():
            self.assertEqual(fields[column].get_default(), empty, column)

    def test_calculation_details_is_not_retired(self):
        """recompute_soil_carbon writes its method marker there."""
        self.assertNotIn("calculation_details", RETIRED_CARBON_ENTRY_COLUMNS)


class _Farm(_FarmMixin, TestCase):
    pass


class TheWriterTests(_Farm):
    def test_an_entry_written_from_an_event_leaves_every_retired_column_empty(self):
        entry = EventCarbonCalculator().create_carbon_entry_from_event(
            self.event, {"co2e": 1.5, "verification_status": "estimated", "data_source": "test"}
        )
        entry.refresh_from_db()
        for column, empty in RETIRED_CARBON_ENTRY_COLUMNS.items():
            self.assertEqual(getattr(entry, column), empty, column)


class ClearCommandTests(_Farm):
    def test_dry_run_apply_check_and_restore(self):
        held = self._entry(**LEGACY_VALUES)
        clean = self._entry()

        dry = self._run("dry.json")
        self.assertEqual([c["pk"] for c in dry["changes"]], [held.pk])
        self.assertEqual(dry["changes"][0]["before"], LEGACY_VALUES)
        held.refresh_from_db()
        self.assertEqual(held.verification_notes, LEGACY_VALUES["verification_notes"])  # dry run wrote nothing
        self.assertFalse(DataOperationLog.objects.filter(operation="clear_retired_carbon_columns").exists())

        count = CarbonEntry.objects.count()
        self._run("apply.json", "--apply")
        held.refresh_from_db()
        for column, empty in RETIRED_CARBON_ENTRY_COLUMNS.items():
            self.assertEqual(getattr(held, column), empty, column)
        self.assertEqual((held.description, held.amount), ("Diesel", 2))  # only the retired columns
        self.assertEqual(CarbonEntry.objects.count(), count)
        self.assertEqual(self._run("check.json")["changes"], [])

        log = DataOperationLog.objects.get(operation="clear_retired_carbon_columns")
        call_command("clear_retired_carbon_columns", "--restore", f"log:{log.pk}", stdout=open(os.devnull, "w"))
        held.refresh_from_db()
        for column, value in LEGACY_VALUES.items():
            self.assertEqual(getattr(held, column), value, column)
        clean.refresh_from_db()
        self.assertEqual(clean.verification_notes, "")

    def test_restore_refuses_a_column_that_is_not_retired(self):
        from django.core.management.base import CommandError

        from carbon.management.commands.clear_retired_carbon_columns import write

        entry = self._entry()
        with self.assertRaises(CommandError):
            write("carbon.CarbonEntry", entry.pk, {"amount": 0})
        entry.refresh_from_db()
        self.assertEqual(entry.amount, 2)


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
        self._entry(**LEGACY_VALUES)
        self._entry()
        facts = census._retiring_column_facts()["carbon.CarbonEntry"]
        self.assertEqual(set(facts), set(RETIRED_CARBON_ENTRY_COLUMNS))
        for column in RETIRED_CARBON_ENTRY_COLUMNS:
            self.assertEqual(facts[column], 1 if column in LEGACY_VALUES else 0, column)

    def test_a_drop_is_a_loss_until_the_values_are_cleared(self):
        self._entry(**LEGACY_VALUES)
        dropped = sorted(RETIRED_CARBON_ENTRY_COLUMNS)

        held = census.take_census(label="held")
        result = census.compare(held, _drop(held, "carbon.CarbonEntry", dropped))
        self.assertFalse(result["ok"])
        [loss] = [x for x in result["losses"] if "still held a value" in x]
        self.assertIn("'verification_notes': 1", loss)
        self.assertNotIn("iot_device_id", loss)  # empty everywhere: not a loss

        self._run("apply.json", "--apply")
        cleared = census.take_census(label="cleared")
        result = census.compare(cleared, _drop(cleared, "carbon.CarbonEntry", dropped))
        self.assertTrue(result["ok"], result["losses"])
        self.assertTrue(any("retired columns dropped" in note for note in result["notes"]))

    def test_an_undeclared_column_still_counts_as_a_loss(self):
        self._entry()
        snapshot = census.take_census(label="x")
        result = census.compare(snapshot, _drop(snapshot, "carbon.CarbonEntry", ["description"]))
        self.assertIn("carbon.CarbonEntry: columns dropped ['description']", result["losses"])
