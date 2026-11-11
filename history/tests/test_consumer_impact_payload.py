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

`clear_impact_summaries` emptied the stored rows in production through `data_operations`, and
history 0256 retired the model with it (`test_retired_impact_summary` holds that).
"""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import GeneralEvent, History, HistoryScan, ProductionEvent
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
        self.assertEqual(data["quick_stats"], {"documented_products": 1})

    def test_no_retired_field_reaches_the_wire(self):
        data = _get(self.shopper)
        served = json.dumps({"impact_metrics": data["impact_metrics"], "quick_stats": data["quick_stats"]})
        self.assertIn("documented_products", served)  # the check read the payload
        for word in RETIRED_WORDS:
            self.assertNotIn(word, served.lower(), word)


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
