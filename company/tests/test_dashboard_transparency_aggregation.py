"""Farm-level transparency aggregation.

The farm headline used to average EVERY History row on the establishment. Two consequences,
both of which showed up on a real pilot farm:

1. An unpublished draft (or an internal test production) scored 0 and was averaged in, so a
   farm whose only finished season scored 74 was displayed as 37 — a "D".
2. Starting a new season necessarily added a near-zero row, so the headline dropped the moment
   a grower did the one thing the product exists to encourage. That is exactly backwards during
   the Oct-Feb postharvest window when growers onboard and open their next season.

Only FINISHED, published seasons carry a verdict. A farm with none returns None, not 0 —
"no verdict yet" must not render as a failing grade.
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from company.serializers import EstablishmentDashboardMetricsSerializer
from history.models import History, ProductionEvent
from product.models import Parcel, Product


class FarmTransparencyAggregationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Aggregation Farm")
        # `state` is required: saving an event fires the carbon signal, which builds a
        # USDAComplianceRecord whose `state` column is NOT NULL with no default.
        self.establishment = Establishment.objects.create(name="Agg1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="AggP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Walnuts")
        self.serializer = EstablishmentDashboardMetricsSerializer()

    def _production(self, *, published, finished, name, events=0):
        history = History.objects.create(
            name=name,
            start_date=timezone.now() - timezone.timedelta(days=200),
            finish_date=timezone.now() - timezone.timedelta(days=10) if finished else None,
            product=self.product,
            parcel=self.parcel,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=published,
        )
        for _ in range(events):
            ProductionEvent.objects.create(history=history, type="PL", date=timezone.now())
        return history

    def _metrics(self):
        return self.serializer.get_metrics_for_establishment(self.establishment)

    def test_unpublished_draft_does_not_lower_the_farm_score(self):
        self._production(published=True, finished=True, name="Finished season", events=6)
        finished_only = self._metrics()["transparency_score"]

        # The regression: adding a zero-event draft used to halve the headline.
        self._production(published=False, finished=False, name="Untitled draft")
        with_draft = self._metrics()["transparency_score"]

        self.assertEqual(
            with_draft,
            finished_only,
            "an unpublished draft changed the farm score — drafts must not be averaged in",
        )

    def test_starting_a_new_season_does_not_lower_the_farm_score(self):
        self._production(published=True, finished=True, name="Finished season", events=6)
        before = self._metrics()["transparency_score"]

        # A season that has just opened has no events yet; that is not poor documentation.
        self._production(published=True, finished=False, name="2027 season")
        after = self._metrics()

        self.assertEqual(
            after["transparency_score"],
            before,
            "opening a new season lowered the farm score — in-progress seasons must be excluded",
        )
        self.assertEqual(after["productions_in_progress"], 1)
        self.assertEqual(after["scored_productions"], 1)

    def test_no_finished_season_returns_none_not_zero(self):
        self._production(published=True, finished=False, name="Only season, underway")
        metrics = self._metrics()

        self.assertIsNone(
            metrics["transparency_score"],
            "a farm mid-season reported 0% — that reads as a failing grade for work still underway",
        )
        self.assertEqual(metrics["transparency_tier"], "not_started")
        self.assertEqual(metrics["scored_productions"], 0)
        self.assertEqual(metrics["productions_in_progress"], 1)

    def test_finished_season_with_no_events_still_scores_zero(self):
        # Excluding in-progress seasons must not become a way to hide a genuinely
        # undocumented one: a season the farmer finished and published with nothing
        # logged really is 0% documented.
        self._production(published=True, finished=True, name="Finished, undocumented")
        metrics = self._metrics()

        self.assertEqual(metrics["transparency_score"], 0.0)
        self.assertEqual(metrics["scored_productions"], 1)

    def test_score_averages_only_finished_seasons(self):
        self._production(published=True, finished=True, name="Season A", events=6)
        self._production(published=True, finished=True, name="Season B", events=6)
        self._production(published=False, finished=False, name="Draft")
        self._production(published=True, finished=False, name="Underway")

        metrics = self._metrics()
        self.assertEqual(metrics["scored_productions"], 2)
        self.assertEqual(metrics["total_productions"], 4)
        self.assertEqual(metrics["productions_in_progress"], 2)
