"""Farm-level dashboard metrics carry COUNTS, never a farm-level score.

Until 2026-09-05 `get_metrics_for_establishment` averaged a full TransparencyCalculator run over
every finished, published season into `transparency_score` (+ a `transparency_tier` label). That
was 282 SQL queries and ~3 s in production on every farm-dashboard load, and nothing rendered the
result — the card reads counts, and the score's only reader was a nudge gated behind 1,000
monthly scans. The tests that pinned HOW the average was taken (drafts excluded, in-progress
seasons excluded, None-not-zero) went with it; what remains pins the facts the card shows.
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

    def test_no_farm_level_score_or_tier_in_metrics(self):
        self._production(published=True, finished=True, name="Finished", events=3)
        metrics = self._metrics()
        for graded in ("transparency_score", "transparency_tier"):
            self.assertNotIn(graded, metrics, f"farm-level '{graded}' crept back into dashboard_metrics")

    def test_finished_seasons_are_counted_not_scored(self):
        self._production(published=True, finished=True, name="Finished A", events=3)
        self._production(published=True, finished=True, name="Finished B", events=0)
        self._production(published=False, finished=True, name="Finished draft", events=2)
        self._production(published=True, finished=False, name="In progress", events=1)
        metrics = self._metrics()
        # Finished AND published only — a finished-but-unpublished season is neither counted nor underway.
        self.assertEqual(metrics["scored_productions"], 2)
        self.assertEqual(metrics["total_productions"], 4)
        self.assertEqual(metrics["productions_in_progress"], 1)
        self.assertEqual(metrics["total_documented_events"], 6)
