"""The daily USDA mirror refresh (2026-11-13): when it downloads, imports, re-verifies or fails.

The download, the import command and the re-verification are faked; these pin the decisions, which
are the part that went wrong (nothing ever ran the import, so the mirror was 104 days old).
"""

import io
import os
import tempfile
from datetime import date, datetime
from datetime import timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from certifications.management.commands import refresh_usda_organic_mirror as cmd
from certifications.models import IngestionRun, USDAOrganicOperation

NOV_13 = datetime(2026, 11, 13, 17, 0, tzinfo=dt_timezone.utc)


def _hold(snapshot):
    USDAOrganicOperation.objects.create(
        op_name="Held Farm",
        op_name_normalized="held",
        state="Washington",
        country="United States of America (the)",
        status="Certified",
        data_snapshot_date=snapshot,
    )


def _mark_reverified(snapshot):
    IngestionRun.objects.create(
        source="usda_organic", status="ok", message=f"{cmd.REVERIFIED_PREFIX}{snapshot}: 1 checked, 0 changed"
    )


class RefreshTests(TestCase):
    def _run(self, published, reverify_error=None, import_error=None):
        """Run with USDA publishing exactly the months in `published` (first-of-month dates)."""
        downloaded, imports = [], []
        self.downloaded = downloaded

        def fake_download(url, out, err):
            for month in published:
                if month.strftime("%Y%m%d") in url:
                    fd, path = tempfile.mkstemp(suffix=".xlsx")
                    os.close(fd)
                    downloaded.append((month, path))
                    return path
            return None

        def fake_call(name, **kwargs):
            if name != "import_usda_organic_data":
                raise AssertionError(f"unexpected command {name}")
            if import_error:
                raise import_error
            imports.append(kwargs)
            _hold(datetime.strptime(kwargs["date"], "%Y%m%d").date())

        manager = MagicMock()
        if reverify_error:
            manager.reverify_all_active.side_effect = reverify_error
        else:
            manager.reverify_all_active.return_value = {"total": 3, "changed": 1}

        with (
            patch.object(cmd.timezone, "now", return_value=NOV_13),
            patch.object(cmd, "download_export", side_effect=fake_download),
            patch.object(cmd, "call_command", side_effect=fake_call),
            patch.object(cmd, "VerificationManager", return_value=manager),
        ):
            call_command("refresh_usda_organic_mirror", stdout=io.StringIO(), stderr=io.StringIO())
        return downloaded, imports, manager.reverify_all_active

    def test_current_and_reverified_mirror_does_nothing(self):
        _hold(date(2026, 11, 1))
        _mark_reverified(date(2026, 11, 1))
        downloaded, imports, reverify = self._run(published=[date(2026, 11, 1)])
        self.assertEqual(downloaded, [])
        self.assertEqual(imports, [])
        reverify.assert_not_called()

    def test_new_month_is_imported_with_its_own_date_then_reverified(self):
        _hold(date(2026, 10, 1))
        _mark_reverified(date(2026, 10, 1))
        downloaded, imports, reverify = self._run(published=[date(2026, 11, 1), date(2026, 10, 1)])
        self.assertEqual([m for m, _ in downloaded], [date(2026, 11, 1)])
        self.assertEqual(imports[0]["date"], "20261101", "the snapshot must carry USDA's month, not today")
        self.assertEqual(imports[0]["file"], downloaded[0][1])
        reverify.assert_called_once()
        self.assertGreaterEqual(reverify.call_args.kwargs["days_ahead"], 36500, "every certification, not 30 days")
        self.assertTrue(cmd._reverified(date(2026, 11, 1)), "the re-verification was not recorded")
        self.assertFalse(os.path.exists(downloaded[0][1]), "the 37 MB export was left on the job's disk")

    def test_a_failed_reverification_is_retried_the_next_run(self):
        """Review on #417: the import commits on its own, so a current mirror is not proof of fresh results."""
        _hold(date(2026, 10, 1))
        _mark_reverified(date(2026, 10, 1))
        with self.assertRaisesMessage(RuntimeError, "boom"):
            self._run(published=[date(2026, 11, 1)], reverify_error=RuntimeError("boom"))
        self.assertFalse(cmd._reverified(date(2026, 11, 1)))

        downloaded, imports, reverify = self._run(published=[date(2026, 11, 1)])
        self.assertEqual(downloaded, [], "the mirror is current; nothing to download")
        reverify.assert_called_once()
        self.assertTrue(cmd._reverified(date(2026, 11, 1)))

    def test_a_snapshot_imported_by_hand_is_reverified_once(self):
        _hold(date(2026, 11, 1))
        _mark_reverified(date(2026, 10, 1))
        _, _, reverify = self._run(published=[date(2026, 11, 1)])
        reverify.assert_called_once()
        _, _, again = self._run(published=[date(2026, 11, 1)])
        again.assert_not_called()

    def test_unpublished_month_with_last_month_held_is_not_a_failure(self):
        _hold(date(2026, 10, 1))
        _mark_reverified(date(2026, 10, 1))
        downloaded, imports, reverify = self._run(published=[date(2026, 10, 1)])
        self.assertEqual(downloaded, [], "last month is already held; re-importing it is wasted work")
        self.assertEqual(imports, [])
        reverify.assert_not_called()

    def test_two_months_behind_falls_back_to_last_month(self):
        _hold(date(2026, 8, 1))
        try:
            downloaded, imports, reverify = self._run(published=[date(2026, 10, 1)])
        except CommandError as exc:
            self.fail(f"October was published and the mirror holds August, yet the run failed: {exc}")
        self.assertEqual([m for m, _ in downloaded], [date(2026, 10, 1)])
        self.assertEqual(imports[0]["date"], "20261001")
        reverify.assert_called_once()

    def test_stale_and_nothing_downloadable_fails_the_run(self):
        _hold(date(2026, 8, 1))
        with self.assertRaisesMessage(CommandError, "stale data"):
            self._run(published=[])

    def test_empty_mirror_and_nothing_downloadable_fails_the_run(self):
        with self.assertRaisesMessage(CommandError, "holds nothing"):
            self._run(published=[])

    def test_a_refused_import_skips_reverification_and_still_cleans_up(self):
        _hold(date(2026, 10, 1))
        with self.assertRaisesMessage(CommandError, "Refusing"):
            self._run(published=[date(2026, 11, 1)], import_error=CommandError("Refusing to replace"))
        self.assertFalse(cmd._reverified(date(2026, 11, 1)))
        self.assertEqual(len(self.downloaded), 1)
        self.assertFalse(os.path.exists(self.downloaded[0][1]), "a refused import left the export on disk")

    def test_january_falls_back_to_december(self):
        self.assertEqual(cmd._previous_month(date(2027, 1, 1)), date(2026, 12, 1))
