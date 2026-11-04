"""The report of an applied data operation survives the machine that ran it (2026-11-04).

`data_operations.run(apply=True)` wrote its report, the only record of what an apply changed, to a
local file. In production the command runs in an App Platform container whose disk is discarded on
the next deploy or restart, so `--restore <file>` had nothing to read by the time anyone needed it.
The applied `DataOperationLog` row now carries the report text, and `--restore log:<id>` restores
from it under the same guard as a file: the text must hash to a logged apply.
"""

import tempfile
from pathlib import Path

from django.test import TestCase

from common.models import DataOperationLog, Gallery, GalleryImage
from common.services import data_operations as ops

OPERATION = "test_report_in_db"


def _write(model_label, pk, values):
    assert model_label == "common.GalleryImage"
    GalleryImage.objects.filter(pk=pk).update(**values)


class ReportStoredOnTheLogTests(TestCase):
    def setUp(self):
        self.image = GalleryImage.objects.create(gallery=Gallery.objects.create(), s3_key="before/key.jpg")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "report.json")

    def _plan(self):
        return [
            ops.RowChange(
                model="common.GalleryImage",
                pk=self.image.pk,
                before={"s3_key": "before/key.jpg"},
                after={"s3_key": "after/key.jpg"},
                reason="test",
            )
        ]

    def _apply(self):
        ops.run(operation=OPERATION, plan=self._plan, write=_write, report_path=self.path, apply=True)
        return DataOperationLog.objects.get(operation=OPERATION, action=DataOperationLog.ACTION_APPLY)

    def test_the_applied_row_carries_the_exact_report_text(self):
        log = self._apply()
        text = Path(self.path).read_text()
        self.assertEqual(log.report, text)
        self.assertEqual(log.report_sha256, ops.sha256_text(log.report))

    def test_a_dry_run_logs_nothing(self):
        ops.run(operation=OPERATION, plan=self._plan, write=_write, report_path=self.path, apply=False)
        self.assertFalse(DataOperationLog.objects.filter(operation=OPERATION).exists())

    def test_restore_from_the_log_after_the_file_is_gone(self):
        log = self._apply()
        self.image.refresh_from_db()
        self.assertEqual(self.image.s3_key, "after/key.jpg")

        Path(self.path).unlink()  # the container restarted
        ops.restore(operation=OPERATION, report_path=f"log:{log.pk}", write=_write)

        self.image.refresh_from_db()
        self.assertEqual(self.image.s3_key, "before/key.jpg")
        restored = DataOperationLog.objects.get(operation=OPERATION, action=DataOperationLog.ACTION_RESTORE)
        self.assertEqual(restored.report_sha256, log.report_sha256)
        self.assertEqual(restored.report, log.report)

    def test_restore_from_a_file_still_works(self):
        self._apply()
        ops.restore(operation=OPERATION, report_path=self.path, write=_write)
        self.image.refresh_from_db()
        self.assertEqual(self.image.s3_key, "before/key.jpg")

    def test_unknown_or_non_apply_log_ids_restore_nothing(self):
        log = self._apply()
        restore_row = DataOperationLog.objects.create(
            operation=OPERATION, action=DataOperationLog.ACTION_RESTORE, report_sha256="x", report=log.report
        )
        for ref in (f"log:{restore_row.pk}", "log:999999", "log:abc"):
            with self.subTest(ref=ref), self.assertRaises(ops.ReportError):
                ops.restore(operation=OPERATION, report_path=ref, write=_write)
        self.image.refresh_from_db()
        self.assertEqual(self.image.s3_key, "after/key.jpg")

    def test_an_apply_row_without_a_stored_report_restores_nothing(self):
        """Before 2026-11-04, or logged directly by a command that keeps no report."""
        legacy = DataOperationLog.objects.create(
            operation=OPERATION, action=DataOperationLog.ACTION_APPLY, report_sha256="0" * 64
        )
        with self.assertRaisesMessage(ops.ReportError, "stores no report text"):
            ops.restore(operation=OPERATION, report_path=f"log:{legacy.pk}", write=_write)

    def test_an_edited_log_report_is_refused(self):
        """The stored text gets the same guard as a file: it must hash to a logged apply."""
        log = self._apply()
        DataOperationLog.objects.filter(pk=log.pk).update(report=log.report.replace("before/key.jpg", "evil"))
        with self.assertRaises(ops.ReportError):
            ops.restore(operation=OPERATION, report_path=f"log:{log.pk}", write=_write)
        self.image.refresh_from_db()
        self.assertEqual(self.image.s3_key, "after/key.jpg")

    def test_a_report_of_another_operation_is_refused(self):
        """Review of back #287: a mistyped log id passed every hash guard and was written."""
        log = self._apply()
        for ref in (f"log:{log.pk}", self.path):
            with self.subTest(ref=ref), self.assertRaisesMessage(ops.ReportError, "not of 'some_other_operation'"):
                ops.restore(operation="some_other_operation", report_path=ref, write=_write)
        self.image.refresh_from_db()
        self.assertEqual(self.image.s3_key, "after/key.jpg")
        self.assertFalse(DataOperationLog.objects.filter(action=DataOperationLog.ACTION_RESTORE).exists())
