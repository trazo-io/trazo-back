"""Compliance reference data must be able to report that it is missing or stale.

Both datasets here fail silently by nature — an unseeded National List makes the CFR classifier
return early, and a stale USDA mirror produces confident-but-wrong badge decisions in BOTH
directions. Before 2026-08-07 nothing could report either condition: `health_check()` only asked
`count() == 0`, so a five-year-old mirror answered "healthy".
"""

from datetime import date, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from certifications.models import NationalListSubstance, USDAOrganicOperation
from certifications.services.reference_data_status import (
    USDA_SNAPSHOT_CRITICAL_DAYS,
    USDA_SNAPSHOT_STALE_DAYS,
    national_list_status,
    reference_data_report,
    reset_reference_data_cache,
    usda_snapshot_status,
)


class ReportCacheResetMixin:
    """`reference_data_report` memoises in-process for 5 minutes.

    Without an explicit reset, the first test to call it would pin the answer for every later
    test in the same process, and results would depend on test ORDER.
    """

    def setUp(self):
        super().setUp()
        reset_reference_data_cache()
        self.addCleanup(reset_reference_data_cache)


def _load_snapshot(*, days_old, count=3):
    snapshot_date = timezone.now().date() - timedelta(days=days_old)
    USDAOrganicOperation.objects.bulk_create(
        [
            USDAOrganicOperation(
                op_name=f"Farm {i}",
                op_name_normalized=f"{i}",
                state="CA",
                country="United States of America",
                status="Certified",
                data_snapshot_date=snapshot_date,
            )
            for i in range(count)
        ]
    )
    return snapshot_date


class NationalListStatusTests(TestCase):
    def test_unseeded_is_reported_with_the_command_that_fixes_it(self):
        result = national_list_status()
        self.assertFalse(result["seeded"])
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["remediation"], "manage.py seed_national_list")
        # The detail has to say what breaks, not merely that a table is empty — the consequence
        # (empty certifier findings) is the part an operator needs to weigh.
        self.assertIn("certifier findings", result["detail"])

    def test_the_handling_rows_every_database_carries_do_not_count_as_seeded(self):
        """🔴 2026-09-10 — migration 0038 seeds § 205.605 handling rows everywhere. Counting any row
        reported a never-seeded database as "ok" while chemical inputs went unclassified."""
        self.assertTrue(NationalListSubstance.objects.filter(cfr_section="205.605").exists())
        self.assertFalse(national_list_status()["seeded"])

    def test_seeded_reports_ok_with_a_count(self):
        NationalListSubstance.objects.create(
            substance_name="Copper sulfate",
            substance_name_normalized="copper sulfate",
            cfr_section="205.601",
        )
        result = national_list_status()
        self.assertTrue(result["seeded"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 1)
        self.assertIsNone(result["remediation"])


class UsdaSnapshotStatusTests(TestCase):
    def test_empty_mirror_is_missing(self):
        result = usda_snapshot_status()
        self.assertFalse(result["loaded"])
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["remediation"], "manage.py import_usda_organic_data")

    def test_fresh_snapshot_is_ok(self):
        _load_snapshot(days_old=5)
        result = usda_snapshot_status()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["age_days"], 5)
        self.assertIsNone(result["remediation"])

    def test_snapshot_past_the_stale_threshold_is_stale(self):
        _load_snapshot(days_old=USDA_SNAPSHOT_STALE_DAYS + 1)
        result = usda_snapshot_status()
        self.assertEqual(result["status"], "stale")
        # Both failure directions are named, because they are opposite and both are wrong.
        self.assertIn("Pending Verification", result["detail"])
        self.assertIn("surrendered", result["detail"])

    def test_snapshot_just_under_the_stale_threshold_is_still_ok(self):
        _load_snapshot(days_old=USDA_SNAPSHOT_STALE_DAYS - 1)
        self.assertEqual(usda_snapshot_status()["status"], "ok")

    def test_very_old_snapshot_escalates_to_critical(self):
        _load_snapshot(days_old=USDA_SNAPSHOT_CRITICAL_DAYS + 1)
        self.assertEqual(usda_snapshot_status()["status"], "critical")

    def test_the_march_scenario_that_prompted_this(self):
        # Prod was reportedly stamped 2026-03-01 while October pilots were being planned.
        USDAOrganicOperation.objects.create(
            op_name="Real Farm",
            op_name_normalized="real",
            state="CA",
            country="United States of America",
            status="Certified",
            data_snapshot_date=date(2026, 3, 1),
        )
        result = usda_snapshot_status()
        self.assertIn(result["status"], ("stale", "critical"))
        self.assertEqual(result["snapshot_date"], "2026-03-01")

    def test_snapshot_date_is_mandatory_so_freshness_is_always_knowable(self):
        # The service carries an "unknown" branch for undated rows. It is unreachable today
        # BECAUSE of this constraint — asserted here so that relaxing the field is a deliberate
        # act that fails this test, rather than a silent way to make freshness unknowable.
        field = USDAOrganicOperation._meta.get_field("data_snapshot_date")
        self.assertFalse(field.null, "data_snapshot_date became nullable — see usda_snapshot_status()")

    def test_newest_snapshot_date_wins_when_rows_disagree(self):
        _load_snapshot(days_old=400, count=2)
        _load_snapshot(days_old=3, count=2)
        self.assertEqual(usda_snapshot_status()["age_days"], 3)


class ReferenceDataReportTests(ReportCacheResetMixin, TestCase):
    def test_overall_is_the_worst_dataset_not_the_average(self):
        NationalListSubstance.objects.create(
            substance_name="Copper sulfate",
            substance_name_normalized="copper sulfate",
            cfr_section="205.601",
        )
        # National List ok, USDA missing entirely.
        report = reference_data_report()
        self.assertEqual(report["overall"], "missing")
        self.assertEqual(report["datasets"]["national_list"]["status"], "ok")

    def test_all_good_reports_ok_and_no_actions(self):
        NationalListSubstance.objects.create(
            substance_name="Copper sulfate",
            substance_name_normalized="copper sulfate",
            cfr_section="205.601",
        )
        _load_snapshot(days_old=1)
        report = reference_data_report()
        self.assertEqual(report["overall"], "ok")
        self.assertEqual(report["action_required"], [])

    def test_action_required_lists_every_command_to_run(self):
        report = reference_data_report()
        self.assertEqual(
            sorted(report["action_required"]),
            ["manage.py import_usda_organic_data", "manage.py seed_national_list"],
        )


class ReportCachingTests(ReportCacheResetMixin, TestCase):
    """The report is memoised because /health/ is polled continuously by orchestration."""

    def test_repeat_calls_do_not_requery(self):
        # Measured before caching: ~7.4 ms and 3 queries per call, including a COUNT(*) over
        # ~37k rows and an ORDER BY on an unindexed column — on the liveness path.
        #
        # The COLD count is deliberately not pinned to a literal: it varies with the data, because
        # `usda_snapshot_status` returns early after its COUNT when the mirror is empty and never
        # runs the snapshot-date query. Pinning "3" made this pass only when the mirror happened
        # to hold rows. The invariant worth asserting is that the SECOND call touches the database
        # not at all.
        _load_snapshot(days_old=1)
        reset_reference_data_cache()

        with CaptureQueriesContext(connection) as cold:
            reference_data_report()
        self.assertGreater(len(cold.captured_queries), 0, "the cold call should hit the database")

        with self.assertNumQueries(0):
            reference_data_report()
            reference_data_report()

    def test_use_cache_false_always_recomputes(self):
        reference_data_report()
        with CaptureQueriesContext(connection) as forced:
            reference_data_report(use_cache=False)
        self.assertGreater(
            len(forced.captured_queries),
            0,
            "use_cache=False must recompute, not serve the memoised report",
        )

    def test_a_stale_cache_entry_is_not_served_after_a_reset(self):
        first = reference_data_report()
        self.assertEqual(first["overall"], "missing")

        NationalListSubstance.objects.create(
            substance_name="Copper sulfate",
            substance_name_normalized="copper sulfate",
            cfr_section="205.601",
        )
        _load_snapshot(days_old=1)

        # Still cached — this is the intended trade: a few minutes of staleness in a STATUS
        # REPORT about data that changes monthly.
        self.assertEqual(reference_data_report()["overall"], "missing")

        reset_reference_data_cache()
        self.assertEqual(reference_data_report()["overall"], "ok")


class NationalListSkipIsAudibleTests(TestCase):
    """`history/signals.py` used to `return  # skip silently` when the list was unseeded."""

    def setUp(self):
        import history.signals as signals

        signals._warned_national_list_unseeded = False
        self.signals = signals

    def _fire(self):
        from history.models import ChemicalEvent

        event = ChemicalEvent(commercial_name="Roundup PowerMax 3")
        self.signals.auto_classify_chemical_against_national_list(sender=ChemicalEvent, instance=event)

    def test_unseeded_list_now_logs_a_warning_naming_the_consequence(self):
        with self.assertLogs("history.signals", level="WARNING") as captured:
            self._fire()
        message = "\n".join(captured.output)
        self.assertIn("seed_national_list", message)
        # An operator must be able to tell this is a deployment gap, not a data problem.
        self.assertIn("certifier findings will be empty", message)

    def test_the_warning_fires_once_per_process_not_once_per_event(self):
        # A bulk import saves thousands of ChemicalEvents; one line per event would bury the
        # signal it is meant to raise.
        with self.assertLogs("history.signals", level="WARNING") as captured:
            self._fire()
            self._fire()
            self._fire()
        unseeded_lines = [line for line in captured.output if "seed_national_list" in line]
        self.assertEqual(len(unseeded_lines), 1)

    def test_classification_still_never_blocks_a_save(self):
        # The receiver is advisory; it must return normally rather than raise, seeded or not.
        self._fire()


class HealthEndpointTests(ReportCacheResetMixin, TestCase):
    def test_health_reports_reference_data_without_failing_the_container(self):
        # Stale reference data is a correctness problem for claims, not a reason to pull a
        # serving instance out of rotation — it must be visible but never 503.
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("reference_data", payload["checks"])
        self.assertEqual(payload["checks"]["reference_data"]["overall"], "missing")
        self.assertEqual(payload["status"], "healthy")
