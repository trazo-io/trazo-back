"""The census knows what carbon 0052 retires, one deploy before 0052 runs.

0052 takes CarbonOffsetProject, CarbonOffsetPurchase, CarbonOffsetCertificate, CarbonBenchmark,
CarbonReport and CarbonAuditLog.report out of the model state. The census compares a snapshot
taken before a deploy with one taken after, and it lets a table or a column disappear only when
it was declared retiring AND the snapshot before counted nothing in it. A column's facts are read
by the census taken BEFORE, on the code then deployed, so the declaration has to ship first:
the same order as #318 then #320.

`report_id` also exposed a mismatch: the census lists DATABASE columns, but the retiring facts
were keyed by FIELD name. For CarbonEntry's retired columns the two were the same; for a foreign
key they are not (`report` / `report_id`), and the declaration would have matched nothing.
"""

import copy

from django.test import TestCase, TransactionTestCase

from carbon.models import CarbonAuditLog, CarbonReport
from common.services import census
from company.models import Company, Establishment

AUDIT = "carbon.CarbonAuditLog"
RETIRING_TABLES = {
    "carbon.CarbonBenchmark",
    "carbon.CarbonOffsetCertificate",
    "carbon.CarbonOffsetProject",
    "carbon.CarbonOffsetPurchase",
    "carbon.CarbonReport",
}


def _without_column(snapshot, label, column):
    """`snapshot` as a census would read it once `column` has left `label`'s model."""
    after = copy.deepcopy(snapshot)
    table = after["tables"][label]
    index = table["columns"].index(column)
    width = census.CELL_HASH_CHARS
    for key, row in table["rows"].items():
        digest, cells = row.split(":", 1)
        table["rows"][key] = f"{digest}:{cells[:index * width]}{cells[(index + 1) * width:]}"
    table["columns"].remove(column)
    return after


class TheDeclarationsTests(TestCase):
    def test_the_five_tables_are_declared_retiring(self):
        self.assertTrue(RETIRING_TABLES <= census.RETIRED_TABLES, RETIRING_TABLES - census.RETIRED_TABLES)

    def test_report_id_is_counted_by_its_column_name(self):
        self.assertEqual(census._retiring_column_facts()[AUDIT], {"report_id": 0})

    def test_a_row_naming_a_report_is_counted(self):
        establishment = Establishment.objects.create(name="Report Farm", company=Company.objects.create(name="R"))
        report = CarbonReport.objects.create(establishment=establishment)
        CarbonAuditLog.objects.create(report=report, action="create", details="")
        CarbonAuditLog.objects.create(action="create", details="")  # no report: not counted
        self.assertEqual(census._retiring_column_facts()[AUDIT], {"report_id": 1})


class CensusAcrossTheReportIdDropTests(TransactionTestCase):
    """`TransactionTestCase`: the census opens its own read-only snapshot transaction."""

    def setUp(self):
        CarbonAuditLog.objects.create(action="create", details="an event edit")
        self.before = census.take_census(label="before-0052")
        self.after = _without_column(self.before, AUDIT, "report_id")

    def test_dropping_report_id_counted_empty_is_a_note(self):
        result = census.compare(self.before, self.after)
        self.assertTrue(result["ok"], result["losses"])
        self.assertIn(
            f"{AUDIT}: retired columns dropped, every row held the empty value before: ['report_id']",
            result["notes"],
        )

    def test_dropping_report_id_while_a_row_named_a_report_is_a_loss(self):
        self.before["domain"]["retiring_columns"][AUDIT] = {"report_id": 1}
        result = census.compare(self.before, self.after)
        self.assertFalse(result["ok"])
        self.assertIn(
            f"{AUDIT}: retired columns dropped while rows still held a value {{'report_id': 1}}", result["losses"]
        )

    def test_without_the_declaration_the_drop_is_a_loss(self):
        """What a before-census on the old code would have said."""
        del self.before["domain"]["retiring_columns"][AUDIT]
        result = census.compare(self.before, self.after)
        self.assertIn(f"{AUDIT}: columns dropped ['report_id']", result["losses"])

    def test_a_retiring_table_that_was_empty_may_leave(self):
        after = copy.deepcopy(self.before)
        del after["tables"]["carbon.CarbonReport"]
        result = census.compare(self.before, after)
        self.assertTrue(result["ok"], result["losses"])
        self.assertIn("table carbon.CarbonReport retired, empty before", result["notes"])
