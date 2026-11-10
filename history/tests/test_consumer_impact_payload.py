"""The signed-in consumer dashboard counts a shopper's scans live and stores nothing (2026-11-10).

Until then `impact_dashboard` read and refreshed a `UserImpactSummary` row and served all of it:
`total_carbon_offset_kg` (the scanned seasons' emissions, labelled as an offset),
`miles_driving_offset`, `trees_equivalent`, `sustainable_farms_found`, `better_choices_made`,
points, a level, achievements, plus `recommendations` (always empty) and `achievements` (milestone
badges, one titled "Sustainability Detective"). No screen rendered any of them; a number on the
wire is published whether or not a component draws it.

The "Documented Products" tile rendered `quick_stats.better_choices`, which counted scans of farms
holding a listed certification or, failing that, scans of seasons with USDA-factor carbon
entries. Its tooltip promises products whose producer recorded their farming activities, so it
now gets that count. And "recent scans" took three productions by id, not by date.

`clear_impact_summaries` deletes the stored rows through `data_operations`, so history 0256 can
retire the model; these tests hold its dry run, apply, idempotence and exact restore.
"""

import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from common.models import DataOperationLog
from company.models import Company, Establishment
from history.models import GeneralEvent, History, HistoryScan, ProductionEvent
from history.models_consumer import UserImpactSummary
from product.models import Parcel

URL = "/api/consumer/dashboard/impact_dashboard/"

#: Words of the retired fields and concepts. None may appear in the counts the dashboard serves.
RETIRED_WORDS = ("offset", "miles", "trees", "sustainab", "achievement", "points", "level", "recommendation")


def _parcel(name):
    establishment = Establishment.objects.create(name=name, company=Company.objects.create(name=f"{name} Co"))
    return Parcel.objects.create(name="Block A", establishment=establishment, area=1)


def _production(parcel, name):
    return History.objects.create(name=name, parcel=parcel, start_date=timezone.now())


def _get(user):
    client = APIClient()
    client.force_authenticate(user)
    response = client.get(URL)
    assert response.status_code == 200, response.content
    return response.json()


class TheDashboardCountsLiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.shopper = User.objects.create_user(email="shopper@example.com", password="x")
        cls.other = User.objects.create_user(email="other@example.com", password="x")
        parcel = _parcel("Live Farm")
        cls.documented = _production(parcel, "Documented")
        GeneralEvent.objects.create(history=cls.documented, date=timezone.now())
        ProductionEvent.objects.create(history=cls.documented, type="PL", date=timezone.now())
        cls.withheld_only = _production(parcel, "Buffer only")
        ProductionEvent.objects.create(history=cls.withheld_only, type="BU", date=timezone.now())  # never served
        cls.empty = _production(parcel, "Nothing logged")
        for production in (cls.documented, cls.documented, cls.withheld_only, cls.empty):
            HistoryScan.objects.create(history=production, user=cls.shopper)
        HistoryScan.objects.create(history=cls.documented, user=cls.other)
        HistoryScan.objects.create(history=cls.empty, user=cls.shopper, is_duplicate=True)  # not counted

    def test_the_payload_is_the_shoppers_own_counts(self):
        data = _get(self.shopper)
        self.assertEqual(set(data), {"impact_metrics", "recent_scans", "quick_stats"})
        self.assertEqual(
            data["impact_metrics"],
            {
                "total_scans": 4,
                "verified_farms_scanned": 0,
                "farming_events_viewed": 2,  # the buffer event is withheld from shoppers
                "documented_products": 1,  # scanned twice, counted once; the others show nothing
            },
        )
        self.assertEqual(data["quick_stats"], {"documented_products": 1, "better_choices": 1})

    def test_no_retired_field_reaches_the_wire(self):
        data = _get(self.shopper)
        served = json.dumps({"impact_metrics": data["impact_metrics"], "quick_stats": data["quick_stats"]})
        self.assertIn("documented_products", served)  # the check read the payload
        for word in RETIRED_WORDS:
            self.assertNotIn(word, served.lower(), word)

    def test_the_dashboard_stores_nothing(self):
        _get(self.shopper)
        self.assertFalse(UserImpactSummary.objects.exists())


class RecentScansAreTheMostRecentTests(TestCase):
    """The three productions scanned last, newest first, each once."""

    def test_three_most_recent_productions_by_date_not_by_id(self):
        shopper = get_user_model().objects.create_user(email="recent@example.com", password="x")
        parcel = _parcel("Recent Farm")
        productions = [_production(parcel, f"Season {n}") for n in range(4)]  # ids ascending
        now = timezone.now()
        for age, production in zip((4, 3, 2, 1), productions):  # the lowest id is the oldest scan
            scan = HistoryScan.objects.create(history=production, user=shopper)
            HistoryScan.objects.filter(pk=scan.pk).update(date=now - timedelta(days=age))
        older = HistoryScan.objects.create(history=productions[3], user=shopper)
        HistoryScan.objects.filter(pk=older.pk).update(date=now - timedelta(days=10))

        recent = [scan["production_public_id"] for scan in _get(shopper)["recent_scans"]]
        self.assertEqual(recent, [str(p.public_id) for p in (productions[3], productions[2], productions[1])])


class ClearImpactSummariesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="stored@example.com", password="x")
        self.row = UserImpactSummary.objects.create(
            user=self.user,
            total_scans=3,
            total_carbon_offset_kg=12.5,
            miles_driving_offset=31.0,
            trees_equivalent=0.6,
            achievements_earned=["first_scan"],
            points_earned=30,
            first_scan_date=timezone.now() - timedelta(days=30),
        )
        UserImpactSummary.objects.filter(pk=self.row.pk).update(last_updated=timezone.now() - timedelta(days=200))
        self.stored = UserImpactSummary.objects.values().get(pk=self.row.pk)
        self.dir = Path(tempfile.mkdtemp())

    def _run(self, name, *flags):
        report = self.dir / name
        call_command("clear_impact_summaries", "--report", str(report), *flags, stdout=io.StringIO())
        return json.loads(report.read_text())

    def test_a_dry_run_changes_nothing(self):
        report = self._run("dry.json")
        self.assertEqual([c["pk"] for c in report["changes"]], [self.row.pk])
        self.assertEqual(report["changes"][0]["before"]["total_carbon_offset_kg"], 12.5)
        self.assertTrue(UserImpactSummary.objects.filter(pk=self.row.pk).exists())

    def test_apply_deletes_logs_and_a_second_run_finds_nothing(self):
        self._run("apply.json", "--apply")
        self.assertFalse(UserImpactSummary.objects.exists())
        log = DataOperationLog.objects.get(operation="clear_impact_summaries", action=DataOperationLog.ACTION_APPLY)
        self.assertEqual(log.counts["rows"], 1)
        self.assertEqual(self._run("again.json")["changes"], [])

    def test_restore_puts_every_column_back(self):
        self._run("apply.json", "--apply")
        log = DataOperationLog.objects.get(operation="clear_impact_summaries", action=DataOperationLog.ACTION_APPLY)
        call_command("clear_impact_summaries", "--restore", f"log:{log.pk}", stdout=io.StringIO())
        self.assertEqual(UserImpactSummary.objects.values().get(pk=self.row.pk), self.stored)
