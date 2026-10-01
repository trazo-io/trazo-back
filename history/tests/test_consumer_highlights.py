"""
Tests for the consumer-journey highlight flag on public events.

Phase 2 of the consumer QR redesign curates the default journey view to the
events a shopper actually cares about (planting, harvest, every crop input,
pest interventions, first soil test / first irrigation). The flag is
rule-based and computed at serialization time in
PublicHistorySerializer._annotate_consumer_highlights(); the proof view
ignores it and shows all events.
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, GeneralEvent, History, ProductionEvent, SoilManagementEvent
from history.serializers import PublicHistorySerializer
from product.models import Parcel, Product
from users.models import User


class ConsumerHighlightAnnotationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="hl@test.com", password="x")
        self.company = Company.objects.create(name="Highlight Farm")
        self.establishment = Establishment.objects.create(name="H1", company=self.company)
        self.parcel = Parcel.objects.create(name="HP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Citrus")
        self.history = History.objects.create(
            name="Highlight Test Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _events(self):
        data = PublicHistorySerializer(self.history).data
        return data.get("events") or []

    def test_every_public_event_carries_the_flag(self):
        ProductionEvent.objects.create(history=self.history, type="PL", date=timezone.now())
        GeneralEvent.objects.create(history=self.history, date=timezone.now())
        events = self._events()
        self.assertTrue(events)
        for ev in events:
            self.assertIn("is_highlight", ev)

    def test_planting_and_chemical_inputs_are_highlights(self):
        ProductionEvent.objects.create(history=self.history, type="PL", date=timezone.now())
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Compost Tea",
            date=timezone.now(),
        )
        flags = {e["type"]: e["is_highlight"] for e in self._events()}
        self.assertTrue(flags.get("PL"))
        self.assertTrue(flags.get("chemical"))

    def test_general_events_are_not_highlights(self):
        GeneralEvent.objects.create(history=self.history, date=timezone.now())
        events = self._events()
        general = [e for e in events if e.get("type") == "general"]
        self.assertEqual(len(general), 1)
        self.assertFalse(general[0]["is_highlight"])

    def test_first_soil_test_highlighted_repeats_are_not(self):
        first = SoilManagementEvent.objects.create(
            history=self.history, type="ST", date=timezone.now() - timezone.timedelta(days=2)
        )
        SoilManagementEvent.objects.create(history=self.history, type="ST", date=timezone.now())
        soil = [e for e in self._events() if e.get("type") == "soil_management"]
        self.assertEqual(len(soil), 2)
        # Sorted by date — the earlier test is the highlight, the repeat is not.
        self.assertTrue(soil[0]["is_highlight"])
        self.assertFalse(soil[1]["is_highlight"])
        self.assertEqual(first.type, "ST")
