"""A soil figure built from the area alone is not "from recorded inputs" (AC-14, 2026-10-26).

The Astra activity-capture audit found three soil records badged "De insumos registrados" /
"From recorded inputs" with nothing recorded to compute from:

    pH adjustment, no material, 1 acre      0.12 kg   = 0.3 kg/ha application default x 0.405 ha
    tillage, no fuel, 1 acre                61 kg     = (1.2 kg/ha equipment default
                                                         + 150 kg/ha soil CO2 flux at the
                                                         default "medium" depth) x 0.405 ha
                                                         (flux removed 2026-10-28; now the
                                                         production cultivation diesel
                                                         estimate, 3.2 gal/ha: 13.2 kg)
    lab analysis (irrigation water), 1 acre 0.41 kg   = 1.0 kg/ha "general" fallback x 0.405 ha

`_add_enhanced_usda_metadata` marks every US result `usda_factors_based: True`. The production
path takes that back for its per-hectare estimates (`area_estimate`); the soil path never did, and
the stored entry kept the flag. A lab analysis also had no factor of its own and fell through to
the "general" soil-management default, so a sampling record carried a per-hectare emission.

Recorded inputs on a soil record are the fuel, the lime and the amendment nitrogen: a quantity
the grower entered times a published factor. Those keep the label.
"""

from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from history.models import SoilManagementEvent

ONE_ACRE = Decimal("1")


def _soil(subtype, **fields):
    """An unsaved soil record: the calculator only reads attributes."""
    fields.setdefault("area_covered", ONE_ACRE)
    fields.setdefault("area_unit", "acres")
    event = SoilManagementEvent(type=subtype, **fields)
    event.extra_data = {}
    return event


def _calc(event):
    return EventCarbonCalculator().calculate_soil_management_event_impact(event)


class AreaOnlySoilFiguresAreAreaEstimates(SimpleTestCase):
    def assertAreaEstimate(self, result):
        self.assertGreater(abs(result["co2e"]), 0, "expected a per-hectare figure")
        self.assertFalse(result["usda_factors_based"], "an area estimate was labelled from recorded inputs")
        self.assertEqual(result["verification_status"], "area_estimate")
        self.assertEqual(result["breakdown"]["calculation_basis"], "usda_standard_per_hectare")

    def test_ph_adjustment_with_nothing_recorded_is_not_estimated(self):
        # Its 0.3 kg/ha default came from an unsourced table (review on landing #35, 2026-10-28):
        # with no fuel and no lime on the record there is nothing to estimate from.
        result = _calc(_soil("PA"))
        self.assertEqual(result["co2e"], 0)
        self.assertFalse(result["usda_factors_based"])
        self.assertEqual(result["verification_status"], "no_factor_applied")

    def test_tillage_with_no_fuel_is_an_area_estimate(self):
        """The audit's 61 kg was almost all soil-flux default; that term is gone (2026-10-28,
        `test_soil_carbon_boundary`). What is left is the production cultivation diesel estimate
        (3.2 gal/ha x 10.21 kg/gal), the same factor the methodology page publishes."""
        result = _calc(_soil("TI"))
        self.assertAlmostEqual(result["co2e"], 3.2 * 10.21 * 0.404686, places=2)
        self.assertEqual(result["breakdown"]["fuel_emissions"], 0)
        self.assertAreaEstimate(result)

    def test_cover_crop_with_nothing_recorded_has_no_figure(self):
        # Until 2026-11-11 this was a -0.8 kg/ha soil-carbon credit labelled an area estimate. The
        # soil table carries no credit now (test_soil_carbon_boundary.NoSoilCarbonCredit), so with
        # no fuel and no amendment there is nothing to count: no figure, and never a stored zero.
        result = _calc(_soil("CC"))
        self.assertEqual(result["co2e"], 0)
        self.assertFalse(result["usda_factors_based"])
        self.assertEqual(result["verification_status"], "no_factor_applied")


class LabAnalysisCarriesNoPerHectareEstimate(SimpleTestCase):
    def test_a_water_lab_analysis_is_not_charged_the_general_default(self):
        result = _calc(_soil("LA", sample_matrix="water"))
        self.assertEqual(result["co2e"], 0, "a sampling record was charged a per-hectare emission")
        self.assertFalse(result["usda_factors_based"])
        self.assertNotEqual(result["verification_status"], "factors_verified")
        self.assertEqual(result["calculation_method"], "zero_direct_emissions_manual_sampling")
        self.assertEqual(result["emission_factor_used"]["factor_type"], "soil_test")

    def test_a_lab_analysis_with_recorded_fuel_counts_the_fuel(self):
        result = _calc(_soil("LA", sample_matrix="leaf", fuel_consumed=Decimal("2"), fuel_unit="gal"))
        self.assertAlmostEqual(result["co2e"], 2 * 10.21, delta=0.5)
        self.assertEqual(result["calculation_method"], "fuel_based_soil_sampling")
        self.assertNotEqual(result["verification_status"], "area_estimate")

    def test_a_soil_test_with_nothing_recorded_claims_no_factor(self):
        result = _calc(_soil("ST"))
        self.assertEqual(result["co2e"], 0)
        self.assertFalse(result["usda_factors_based"])
        self.assertEqual(result["verification_status"], "no_factor_applied")


class RecordedInputsKeepTheirLabel(SimpleTestCase):
    """The other half: a figure from a quantity on the record is still a recorded-input figure."""

    def test_tillage_with_recorded_fuel_is_not_an_area_estimate(self):
        result = _calc(_soil("TI", fuel_consumed=Decimal("3"), fuel_unit="gal", fuel_type="diesel"))
        self.assertGreater(result["breakdown"]["fuel_emissions"], 0)
        self.assertNotEqual(result["verification_status"], "area_estimate")

    def test_lime_with_a_recorded_amount_is_not_an_area_estimate(self):
        result = _calc(
            _soil(
                "PA",
                amendment_type="limestone",
                amendment_amount="500 kg",
                amendment_amount_numeric=Decimal("500"),
                amendment_amount_unit="kg",
            )
        )
        self.assertGreater(result["breakdown"]["lime_dissolution_emissions"], 0)
        self.assertNotEqual(result["verification_status"], "area_estimate")


class StoredAndServedSoilCarbon(TestCase):
    """End to end: the signal stores the entry, the serializer serves the card's flags."""

    def setUp(self):
        from company.models import Company, Establishment
        from history.models import History
        from product.models import Parcel, Product
        from users.models import User

        user = User.objects.create_user(email="ac14soil@test.com", password="x")
        est = Establishment.objects.create(name="AC14", company=Company.objects.create(name="AC14 Co"), state="WA")
        self.history = History.objects.create(
            name="Gala 2026",
            start_date=timezone.now(),
            product=Product.objects.create(name="Apples"),
            parcel=Parcel.objects.create(name="Block 3", establishment=est, area=10),
            operator=user,
        )

    def _create(self, subtype, **fields):
        event = SoilManagementEvent.objects.create(
            history=self.history,
            type=subtype,
            date=timezone.now(),
            area_covered=ONE_ACRE,
            area_unit="acres",
            **fields,
        )
        event.refresh_from_db()
        return event

    def _entries(self, event):
        from carbon.models import CarbonEntry

        return CarbonEntry.objects.filter(
            production=self.history, description__icontains=f"SoilManagementEvent(ID={event.id})"
        )

    def _served(self, event):
        from history.serializers import SoilManagementEventSerializer

        return SoilManagementEventSerializer(event).data["carbon_data"]

    def test_tillage_with_no_fuel_is_stored_and_served_as_an_area_estimate(self):
        event = self._create("TI")
        entry = self._entries(event).get()
        self.assertFalse(entry.usda_factors_based, "the stored flag was set back to True")
        self.assertEqual(entry.verification_status, "area_estimate")

        served = self._served(event)
        self.assertGreater(served["co2e"], 0)
        self.assertFalse(served["usda_factors_based"])
        self.assertEqual(served["verification_status"], "area_estimate")

    def test_ph_adjustment_with_nothing_recorded_stores_no_figure(self):
        event = self._create("PA")
        self.assertFalse(self._entries(event).exists(), "a pH adjustment with nothing recorded stored a figure")

    def test_a_lab_analysis_stores_no_figure(self):
        event = self._create("LA", sample_matrix="water")
        self.assertFalse(self._entries(event).exists(), "a sampling record stored a per-hectare emission")
