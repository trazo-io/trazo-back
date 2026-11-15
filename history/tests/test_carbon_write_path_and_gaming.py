"""
Phase 3 / A9 + A8 + A2 + A5 — four carbon defects that shared one theme: the figure did not
follow from the farmer's actual inputs.

A9  `method` was in the READ serializer's EXTRA_DATA_FIELDS but missing from the WRITE list,
    so a flat `method=` POST was silently discarded. That single omission disabled the
    manual-operation short-circuit in the calculator, so a HAND harvest was billed the USDA
    mechanical average. Hand work is normal in a California organic orchard, so the grower
    doing the labour-intensive thing was charged for machinery they never ran.

A8  `_get_structured_production_data` never returned `fuel_type`, while
    `_extract_production_event_data` read it with a "diesel" fallback — so the kg-to-gallons
    density was always diesel's, wrong for gasoline and badly wrong for the propane burned in
    flame weeding.

A2  General events persisted a fabricated 0.1 kg CO2e, gated on a keyword match over the
    event's name and notes. Output depended on the farmer's wording, not on any activity.

A5  A self-assessed efficiency dropdown scaled emissions: choosing "high" cut reported fuel
    emissions 15%. A self-declared discount on a measured quantity is exactly what the
    anti-gaming rules in carbon-methodology.md exist to prevent.
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import GeneralEvent, Production, ProductionEvent
from history.serializers import ProductionEventSerializer, UpdateProductionEventSerializer
from product.models import Parcel, Product
from users.models import User


class MethodWritePathTests(TestCase):
    """A9 — the one-line omission that mispriced every hand operation."""

    def test_method_is_accepted_on_the_write_path(self):
        self.assertIn(
            "method",
            UpdateProductionEventSerializer.EXTRA_DATA_FIELDS,
            "`method` missing from the write serializer again — the manual-operation carbon "
            "short-circuit cannot fire, so hand harvests get the mechanical average",
        )

    def test_write_and_read_field_lists_agree_on_method(self):
        # The original bug was precisely a disagreement between the two lists.
        self.assertIn("method", ProductionEventSerializer.EXTRA_DATA_FIELDS)
        self.assertIn("method", UpdateProductionEventSerializer.EXTRA_DATA_FIELDS)

    def test_flat_method_post_survives_into_extra_data(self):
        data = {
            "type": "HA",
            "date": timezone.now().isoformat(),
            "description": "Hand harvest",
            "area_covered": 5.0,
            "method": "hand",
        }
        internal = UpdateProductionEventSerializer().to_internal_value(data)
        self.assertEqual(
            internal.get("extra_data", {}).get("method"),
            "hand",
            "a flat `method=hand` POST was dropped — this is the exact shape the form sends",
        )


class ManualOperationCarbonTests(TestCase):
    """A9, end to end: a hand harvest must cost less than a mechanical one."""

    def setUp(self):
        self.user = User.objects.create_user(email="manual@test.com", password="x")
        company = Company.objects.create(name="Manual Farm")
        establishment = Establishment.objects.create(name="MF1", company=company, state="CA")
        self.parcel = Parcel.objects.create(name="M-parcel", establishment=establishment, area=10.0)
        self.product = Product.objects.create(name="Walnut")
        self.history = Production.objects.create(
            name="Manual Production",
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
        )

    def _harvest(self, **extra):
        return ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="Harvest",
            area_covered=5.0,
            extra_data=extra or {},
        )

    def _co2e(self, event):
        from carbon.models import CarbonEntry

        entry = CarbonEntry.objects.filter(
            production=self.history, description__icontains=f"ProductionEvent(ID={event.id})"
        ).first()
        if entry:
            return float(entry.co2e_amount or entry.amount or 0.0)
        calc = (event.extra_data or {}).get("carbon_calculation") or {}
        return float(calc.get("co2e", 0.0))

    def test_hand_harvest_costs_less_than_mechanical(self):
        mechanical = self._harvest()
        manual = self._harvest(method="hand")
        self.assertLess(
            self._co2e(manual),
            self._co2e(mechanical),
            "a hand harvest was charged the same as a mechanical one — the manual "
            "short-circuit is not seeing extra_data.method",
        )


class GeneralEventNoCarbonTests(TestCase):
    """A2 — a fabricated constant, gated on wording, is worse than recording nothing."""

    def setUp(self):
        self.user = User.objects.create_user(email="general@test.com", password="x")
        company = Company.objects.create(name="General Farm")
        establishment = Establishment.objects.create(name="GF1", company=company, state="CA")
        parcel = Parcel.objects.create(name="G-parcel", establishment=establishment, area=10.0)
        product = Product.objects.create(name="Almond")
        self.history = Production.objects.create(
            name="General Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _entries(self, event):
        from carbon.models import CarbonEntry

        return CarbonEntry.objects.filter(
            production=self.history, description__icontains=f"GeneralEvent(ID={event.id})"
        )

    def test_no_carbon_entry_is_created(self):
        event = GeneralEvent.objects.create(
            history=self.history, name="Staff training", date=timezone.now(), description="Annual training"
        )
        self.assertEqual(self._entries(event).count(), 0)

    def test_wording_no_longer_changes_the_outcome(self):
        """The keyword gate made "Diesel delivery" emit and "Tractor top-up" not."""
        with_keyword = GeneralEvent.objects.create(
            history=self.history, name="Fuel delivery paperwork", date=timezone.now(), description="Filed invoice"
        )
        without_keyword = GeneralEvent.objects.create(
            history=self.history, name="Team meeting", date=timezone.now(), description="Weekly sync"
        )
        self.assertEqual(self._entries(with_keyword).count(), self._entries(without_keyword).count())
        self.assertEqual(self._entries(with_keyword).count(), 0)

    def test_saving_sweeps_a_legacy_fabricated_entry(self):
        from carbon.models import CarbonEntry

        event = GeneralEvent.objects.create(
            history=self.history, name="Equipment logbook", date=timezone.now(), description="Filed"
        )
        # Simulate a row written by the old fabricated-value path, in the shape its writer
        # (`create_carbon_entry_from_event`) used: the sweep finds rows by that shape or by the
        # activity link, never by a mention anywhere in free text (carbon/event_link.py).
        CarbonEntry.objects.create(
            production=self.history,
            description=f"Auto-calculated from GeneralEvent(ID={event.id}) event: keyword_match",
            registry_verification_id=f"REG-GeneralEvent-{event.id}",
            amount=0.1,
            co2e_amount=0.1,
            type="general",
            year=timezone.now().year,
        )
        self.assertEqual(self._entries(event).count(), 1)

        event.observation = "touched"
        event.save()
        self.assertEqual(
            self._entries(event).count(),
            0,
            "re-saving a general event should purge the legacy fabricated 0.1 kg entry",
        )


class SelfAssessedEfficiencyTests(TestCase):
    """A5 — a dropdown must not let a farmer discount their own measured emissions."""

    def setUp(self):
        self.user = User.objects.create_user(email="eff@test.com", password="x")
        company = Company.objects.create(name="Eff Farm")
        establishment = Establishment.objects.create(name="EF1", company=company, state="CA")
        parcel = Parcel.objects.create(name="E-parcel", establishment=establishment, area=10.0)
        product = Product.objects.create(name="Almond")
        self.history = Production.objects.create(
            name="Eff Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _pest_co2e(self, efficiency):
        from history.models import PestManagementEvent

        event = PestManagementEvent.objects.create(
            history=self.history,
            type="SC",
            date=timezone.now(),
            description="Scouting pass",
            area_covered=5.0,
            fuel_consumed=4.0,
            fuel_unit="gal",
            fuel_type="diesel",
            production_efficiency=efficiency,
        )
        calc = (event.extra_data or {}).get("carbon_calculation") or {}
        return float(calc.get("co2e", 0.0))

    def test_claiming_high_efficiency_does_not_reduce_emissions(self):
        high = self._pest_co2e("high")
        normal = self._pest_co2e("normal")
        low = self._pest_co2e("low")
        self.assertAlmostEqual(high, normal, places=6, msg="'high' efficiency still discounts emissions")
        self.assertAlmostEqual(low, normal, places=6, msg="'low' efficiency still inflates emissions")

    def test_the_same_fuel_always_gives_the_same_emissions(self):
        values = {self._pest_co2e(e) for e in ("high", "normal", "low")}
        self.assertEqual(len(values), 1, f"identical fuel produced different emissions by self-rating: {values}")
