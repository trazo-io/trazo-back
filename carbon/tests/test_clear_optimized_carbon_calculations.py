"""`clear_optimized_carbon_calculations`: dry run, apply, idempotence, restore of every row.

The table is a performance log of a retired 0-100 score that nothing reads. The rows are deleted
before the model retires, through common/services/data_operations, so the applied report (stored on
its DataOperationLog row) is a complete copy and `--restore log:<id>` recreates each row exactly.
"""

import json
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from carbon.models import OptimizedCarbonCalculation
from common.models import DataOperationLog

OPERATION = "clear_optimized_carbon_calculations"


class ClearOptimizedCarbonCalculationsTests(TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        for n, score in ((1, 70.0), (2, 90.0)):
            OptimizedCarbonCalculation.objects.create(
                production_id=f"api_calc_{n}",
                event_type="chemical",
                co2e_total=Decimal("1.250"),
                efficiency_score=score,
                calculation_method="optimized_v2",
                calculation_time_ms=12,
            )
        self.before = sorted(OptimizedCarbonCalculation.objects.values_list("pk", "production_id", "efficiency_score"))

    def _run(self, name, *flags):
        out = StringIO()
        call_command(OPERATION, "--report", str(self.dir / name), *flags, stdout=out)
        return out.getvalue()

    def test_a_dry_run_deletes_nothing_and_reports_every_row(self):
        output = self._run("dry.json")
        self.assertIn("Dry run, nothing saved: 2 row(s)", output)
        self.assertEqual(OptimizedCarbonCalculation.objects.count(), 2)
        self.assertEqual(len(json.loads((self.dir / "dry.json").read_text())["changes"]), 2)
        self.assertFalse(DataOperationLog.objects.filter(operation=OPERATION).exists())

    def test_apply_deletes_every_row_logs_it_and_a_second_run_finds_nothing(self):
        self._run("apply.json", "--apply")
        self.assertEqual(OptimizedCarbonCalculation.objects.count(), 0)
        log = DataOperationLog.objects.get(operation=OPERATION, action=DataOperationLog.ACTION_APPLY)
        self.assertEqual(log.counts["rows"], 2)
        self.assertIn("0 row(s)", self._run("check.json"))

    def test_restore_from_the_log_recreates_every_row_exactly(self):
        self._run("apply.json", "--apply")
        log = DataOperationLog.objects.get(operation=OPERATION, action=DataOperationLog.ACTION_APPLY)
        call_command(OPERATION, "--restore", f"log:{log.pk}", stdout=StringIO())
        after = sorted(OptimizedCarbonCalculation.objects.values_list("pk", "production_id", "efficiency_score"))
        self.assertEqual(after, self.before)
