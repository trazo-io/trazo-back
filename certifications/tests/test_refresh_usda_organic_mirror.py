"""The daily USDA mirror refresh (2026-11-13): when it downloads, imports, re-verifies or fails.

The download and the two downstream commands are faked; these pin the decisions, which are the part
that went wrong (nothing ever ran the import, so the mirror was 104 days old).
"""

import io
import os
import tempfile
from datetime import date, datetime
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from certifications.management.commands import refresh_usda_organic_mirror as cmd
from certifications.models import USDAOrganicOperation

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


class RefreshTests(TestCase):
    def _run(self, published):
        """Run with USDA publishing exactly the months in `published` (first-of-month dates)."""
        downloaded = []

        def fake_download(url, out, err):
            for month in published:
                if month.strftime("%Y%m%d") in url:
                    fd, path = tempfile.mkstemp(suffix=".xlsx")
                    os.close(fd)
                    downloaded.append((month, path))
                    return path
            return None

        calls = []

        def fake_call(name, **kwargs):
            calls.append((name, kwargs))

        with (
            patch.object(cmd.timezone, "now", return_value=NOV_13),
            patch.object(cmd, "download_export", side_effect=fake_download),
            patch.object(cmd, "call_command", side_effect=fake_call),
        ):
            call_command("refresh_usda_organic_mirror", stdout=io.StringIO(), stderr=io.StringIO())
        return downloaded, calls

    def test_current_mirror_downloads_nothing(self):
        _hold(date(2026, 11, 1))
        downloaded, calls = self._run(published=[date(2026, 11, 1)])
        self.assertEqual(downloaded, [])
        self.assertEqual(calls, [])

    def test_new_month_is_imported_with_its_own_date_then_reverified(self):
        _hold(date(2026, 10, 1))
        downloaded, calls = self._run(published=[date(2026, 11, 1), date(2026, 10, 1)])
        self.assertEqual([m for m, _ in downloaded], [date(2026, 11, 1)])
        self.assertEqual([name for name, _ in calls], ["import_usda_organic_data", "reverify_certifications"])
        self.assertEqual(calls[0][1]["date"], "20261101", "the snapshot must carry USDA's month, not today")
        self.assertEqual(calls[0][1]["file"], downloaded[0][1])
        self.assertTrue(calls[1][1].get("all"), "re-verification must cover every certification")
        self.assertFalse(os.path.exists(downloaded[0][1]), "the 37 MB export was left on the job's disk")

    def test_unpublished_month_with_last_month_held_is_not_a_failure(self):
        _hold(date(2026, 10, 1))
        downloaded, calls = self._run(published=[date(2026, 10, 1)])
        self.assertEqual(downloaded, [], "last month is already held; re-importing it is wasted work")
        self.assertEqual(calls, [])

    def test_two_months_behind_falls_back_to_last_month(self):
        _hold(date(2026, 8, 1))
        try:
            downloaded, calls = self._run(published=[date(2026, 10, 1)])
        except CommandError as exc:
            self.fail(f"October was published and the mirror holds August, yet the run failed: {exc}")
        self.assertEqual([m for m, _ in downloaded], [date(2026, 10, 1)])
        self.assertEqual(calls[0][1]["date"], "20261001")
        self.assertEqual(calls[1][0], "reverify_certifications")

    def test_stale_and_nothing_downloadable_fails_the_run(self):
        _hold(date(2026, 8, 1))
        with self.assertRaisesMessage(CommandError, "stale data"):
            self._run(published=[])

    def test_empty_mirror_and_nothing_downloadable_fails_the_run(self):
        with self.assertRaisesMessage(CommandError, "holds nothing"):
            self._run(published=[])

    def test_a_refused_import_skips_reverification_and_still_cleans_up(self):
        _hold(date(2026, 10, 1))
        paths = []

        def fake_download(url, out, err):
            fd, path = tempfile.mkstemp(suffix=".xlsx")
            os.close(fd)
            paths.append(path)
            return path

        def fake_call(name, **kwargs):
            if name == "import_usda_organic_data":
                raise CommandError("Refusing to replace")
            raise AssertionError(f"{name} ran after a refused import")

        with (
            patch.object(cmd.timezone, "now", return_value=NOV_13),
            patch.object(cmd, "download_export", side_effect=fake_download),
            patch.object(cmd, "call_command", side_effect=fake_call),
        ):
            with self.assertRaisesMessage(CommandError, "Refusing"):
                call_command("refresh_usda_organic_mirror", stdout=io.StringIO(), stderr=io.StringIO())
        self.assertFalse(os.path.exists(paths[0]))

    def test_january_falls_back_to_december(self):
        self.assertEqual(cmd._previous_month(date(2027, 1, 1)), date(2026, 12, 1))
