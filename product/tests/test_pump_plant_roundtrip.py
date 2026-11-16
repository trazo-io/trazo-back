"""
Phase 4 / §E-6 — the pumping-plant fields must survive the real write path.

The parcel-compliance card PATCHes multipart/form-data, which cannot carry a JSON null. So
"empty" arrives as an empty string, and DRF's DecimalField/DateField reject "" by default.
Without coercion a farmer could SET a pump test and never CLEAR one — and a stale efficiency
is weaker evidence than none, because pumping plants drift.

This also guards the unit contract: the field is a PERCENT for the farmer (70) and a FRACTION
for the calculator (0.70). A slip either way changes irrigation emissions by ~100x, and
irrigation is the largest energy line in a California orchard.
"""

from django.test import RequestFactory, TestCase

from company.models import Company, Establishment
from product.models import Parcel
from product.serializers import CreateParcelSerializer
from users.models import User


class PumpPlantSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pumpser@test.com", password="x")
        company = Company.objects.create(name="Pump Ser Farm")
        self.establishment = Establishment.objects.create(name="PS1", company=company, state="CA")
        self.parcel = Parcel.objects.create(
            name="ps-parcel",
            establishment=self.establishment,
            area=44.5,
            pump_efficiency_pct=72.5,
            system_pressure_psi=18.0,
            pump_test_provider="Valley Pump Testing",
        )

    def _patch(self, payload):
        # CreateParcelSerializer.update() reads request.FILES for album uploads, so the
        # serializer needs a request in context even for a field-only PATCH.
        request = RequestFactory().patch("/", data={})
        serializer = CreateParcelSerializer(
            instance=self.parcel, data=payload, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_values_round_trip(self):
        parcel = self._patch(
            {
                "pump_efficiency_pct": "68.5",
                "system_pressure_psi": "22.0",
                "pump_test_date": "2026-01-15",
                "pump_test_provider": "PG&E pump test programme",
            }
        )
        self.assertEqual(float(parcel.pump_efficiency_pct), 68.5)
        self.assertEqual(float(parcel.system_pressure_psi), 22.0)
        self.assertEqual(str(parcel.pump_test_date), "2026-01-15")
        self.assertEqual(parcel.pump_test_provider, "PG&E pump test programme")

    def test_blank_strings_clear_the_values(self):
        """The multipart form's only way of saying "empty"."""
        parcel = self._patch({"pump_efficiency_pct": "", "system_pressure_psi": "", "pump_test_date": ""})
        self.assertIsNone(parcel.pump_efficiency_pct)
        self.assertIsNone(parcel.system_pressure_psi)
        self.assertIsNone(parcel.pump_test_date)

    def test_a_parcel_with_no_pump_data_is_valid(self):
        bare = Parcel.objects.create(name="bare", establishment=self.establishment, area=10.0)
        self.assertIsNone(bare.pump_efficiency_pct)
        serializer = CreateParcelSerializer(instance=bare, data={"name": "bare"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_an_out_of_range_efficiency_is_rejected(self):
        # max_digits=4, decimal_places=1 caps this at 999.9; a percentage above 100 is
        # physically impossible for a pumping plant, and the calculator clamps it anyway.
        serializer = CreateParcelSerializer(instance=self.parcel, data={"pump_efficiency_pct": "12345.6"}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("pump_efficiency_pct", serializer.errors)

    def test_percent_is_converted_to_a_fraction_for_the_calculator(self):
        """70 must reach the calculator as 0.70, not 70."""
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        class FakeEvent:
            def __init__(self, parcel):
                class Production:
                    pass

                self.history = Production()
                self.history.parcel = parcel

        attributes = EventCarbonCalculator._parcel_pump_attributes(FakeEvent(self.parcel))
        self.assertAlmostEqual(attributes["pump_efficiency"], 0.725, places=4)
        self.assertEqual(attributes["system_pressure_psi"], 18.0)

    def test_unset_attributes_are_omitted_so_defaults_apply(self):
        """An absent measurement must not override the default with None."""
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        bare = Parcel.objects.create(name="bare2", establishment=self.establishment, area=10.0)

        class FakeEvent:
            def __init__(self, parcel):
                class Production:
                    pass

                self.history = Production()
                self.history.parcel = parcel

        self.assertEqual(EventCarbonCalculator._parcel_pump_attributes(FakeEvent(bare)), {})

    def test_a_detached_event_does_not_raise(self):
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        class Orphan:
            pass

        self.assertEqual(EventCarbonCalculator._parcel_pump_attributes(Orphan()), {})
