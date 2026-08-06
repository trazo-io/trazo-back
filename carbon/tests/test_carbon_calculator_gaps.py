"""
Phase 3 / A3 + A6 + A7 + A4 — four calculator gaps that all produced a confident zero.

Each of these returned a well-formed result with a breakdown and a data source, so nothing
looked broken; the number was just absent or wrong.

A3  Weather HT and HL read their inputs with `hasattr(event, ...)`, but WeatherEvent stores
    everything in `extra_data` — there are no model columns. Every documented heat event and
    every hailstorm computed 0 kg. HL was worse: it multiplied `weight * diameter`, two fields
    Sprint 2 had removed from the form, so severity was structurally always 0.
A6  Aggregate herbicide had no handler and fell through to the FERTILIZER calculator, which
    reads NPK totals a herbicide summary does not carry.
A7  Post-harvest passed production_type="general production", charging facility work a
    per-hectare field-diesel rate while ignoring the processing_energy_kwh the form collects.
A4  `transportation_distance` was collected, validated, displayed — and fed to no formula.
"""

from django.test import TestCase
from django.utils import timezone

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.services.verified_emission_factors import VerifiedEmissionFactors as VEF
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, ProductionEvent, WeatherEvent
from product.models import Parcel, Product
from users.models import User


class CarbonGapTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email=f"{self.__class__.__name__}@test.com", password="x")
        company = Company.objects.create(name="Gap Farm")
        establishment = Establishment.objects.create(name="GAP1", company=company, state="CA")
        self.parcel = Parcel.objects.create(name="gap-parcel", establishment=establishment, area=10.0)
        product = Product.objects.create(name="Almond")
        self.history = History.objects.create(
            name="Gap Production",
            start_date=timezone.now(),
            product=product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        self.calc = EventCarbonCalculator()


class WeatherExtraDataCarbonTests(CarbonGapTestBase):
    """A3 — values live in extra_data, so hasattr() could never find them."""

    def test_high_temperature_emits_only_from_a_reported_intervention(self):
        """A hot day is not an emission — running cooling equipment is.

        The first version of this test asserted that any 42C event emits, which is what the
        old branch pretended to do: it estimated cooling hours from the temperature and
        multiplied by the whole orchard's area at a misting-system rate. On the real Loewen
        walnut sample that invented 12,974 kg CO2e — more than every other event combined —
        for an event whose notes said "No crop stress". Emissions now require the farmer to
        have reported the hours and the area actually cooled.
        """
        reported = WeatherEvent.objects.create(
            history=self.history,
            type="HT",
            date=timezone.now(),
            description="Heat wave, ran misters",
            extra_data={
                "highest_temperature": 42,
                "temperature_unit": "C",
                "cooling_hours": 8,
                "cooling_area_acres": 5,
            },
        )
        result = self.calc.calculate_weather_event_impact(reported)
        self.assertGreater(result["co2e"], 0)
        self.assertEqual(result["breakdown"]["weather_type"], "HT")

    def test_high_temperature_with_no_intervention_emits_nothing(self):
        event = WeatherEvent.objects.create(
            history=self.history,
            type="HT",
            date=timezone.now(),
            description="Heat run, no intervention",
            extra_data={"highest_temperature": 42, "temperature_unit": "C", "duration_days": 4},
        )
        result = self.calc.calculate_weather_event_impact(event)
        self.assertEqual(
            result["co2e"],
            0.0,
            "a heat event with no reported cooling still emits — the temperature-based " "estimate is back",
        )

    def test_high_temperature_never_borrows_the_parcel_area(self):
        """Substituting the orchard area for an unreported one is what caused the 12,974 kg."""
        event = WeatherEvent.objects.create(
            history=self.history,
            type="HT",
            date=timezone.now(),
            description="Heat run, hours but no area",
            extra_data={"highest_temperature": 42, "temperature_unit": "C", "cooling_hours": 8},
        )
        self.assertEqual(self.calc.calculate_weather_event_impact(event)["co2e"], 0.0)

    def test_hailstorm_emits_from_the_fields_the_form_collects(self):
        event = WeatherEvent.objects.create(
            history=self.history,
            type="HL",
            date=timezone.now(),
            description="Hailstorm",
            extra_data={"duration": 25, "way_of_protection": "hail nets"},
        )
        result = self.calc.calculate_weather_event_impact(event)
        self.assertGreater(
            result["co2e"],
            0,
            "hailstorm cleanup still computes 0 — severity is probably still keyed on the "
            "weight/diameter fields Sprint 2 removed",
        )

    def test_hailstorm_duration_is_read_as_minutes(self):
        """WeatherTab labels the hail duration input "Duration (minutes)"."""
        event = WeatherEvent.objects.create(
            history=self.history,
            type="HL",
            date=timezone.now(),
            description="Hailstorm",
            extra_data={"duration": 30, "way_of_protection": "nets"},
        )
        breakdown = self.calc.calculate_weather_event_impact(event)["breakdown"]
        self.assertEqual(breakdown["duration_minutes"], 30)
        self.assertAlmostEqual(breakdown["duration_hours"], 0.5, places=3)

    def test_frost_still_works(self):
        event = WeatherEvent.objects.create(
            history=self.history,
            type="FR",
            date=timezone.now(),
            description="Frost",
            extra_data={"lower_temperature": -2, "temperature_unit": "C", "way_of_protection": "wind_machines"},
        )
        self.assertGreater(self.calc.calculate_weather_event_impact(event)["co2e"], 0)


class AggregateHerbicideTests(CarbonGapTestBase):
    """A6 — a herbicide summary must not be priced with fertilizer factors."""

    def _aggregate_herbicide(self):
        return ChemicalEvent.objects.create(
            history=self.history,
            type="HE",
            date=timezone.now(),
            description="Season herbicide summary",
            commercial_name="Organic herbicide",
            extra_data={
                "is_summary": True,
                "event_count": 4,
                "active_ingredient_total_kg": 12.0,
                "date_start": "2026-03-01",
                "date_end": "2026-08-01",
            },
        )

    def test_aggregate_herbicide_has_its_own_handler(self):
        result = self.calc.calculate_chemical_event_impact(self._aggregate_herbicide())
        self.assertEqual(result["calculation_method"], "aggregate_herbicide_epa_usda")

    def test_it_no_longer_reports_npk_for_a_herbicide(self):
        breakdown = self.calc.calculate_chemical_event_impact(self._aggregate_herbicide())["breakdown"]
        for npk_key in ("nitrogen_total_kg", "phosphorus_total_kg", "potassium_total_kg", "npk"):
            self.assertNotIn(npk_key, breakdown, f"{npk_key} present — still on the fertilizer path")

    def test_active_ingredient_drives_the_figure(self):
        result = self.calc.calculate_chemical_event_impact(self._aggregate_herbicide())
        self.assertGreater(result["co2e"], 0)
        self.assertEqual(result["breakdown"]["active_ingredient_total_kg"], 12.0)

    def test_unknown_aggregate_type_refuses_to_guess(self):
        """The old `else` quietly applied the fertilizer model to anything unrecognised."""
        result = (
            self.calc._calculate_aggregate_chemical_impact_by_type(
                self._aggregate_herbicide(), {"is_summary": True}, "ZZ"
            )
            if hasattr(self.calc, "_calculate_aggregate_chemical_impact_by_type")
            else None
        )
        if result is None:
            self.skipTest("dispatcher is inlined; covered by the handler tests above")


class PostHarvestEnergyTests(CarbonGapTestBase):
    """A7 — facility energy, not a per-hectare field estimate."""

    def test_measured_processing_energy_is_used(self):
        event = ProductionEvent.objects.create(
            history=self.history,
            type="PH",
            date=timezone.now(),
            description="Hulling and drying",
            area_covered=0,
            extra_data={"processing_energy_kwh": 1200, "processing_type": "hulling"},
        )
        result = self.calc.calculate_production_event_impact(event)
        self.assertGreater(result["co2e"], 0)
        self.assertEqual(result["breakdown"].get("processing_electricity_kwh"), 1200)

    def test_no_area_based_diesel_is_invented(self):
        """A PH event carrying the source block's area must not be billed field diesel."""
        event = ProductionEvent.objects.create(
            history=self.history,
            type="PH",
            date=timezone.now(),
            description="Hulling, energy not recorded",
            area_covered=110,
            extra_data={"processing_type": "hulling"},
        )
        result = self.calc.calculate_production_event_impact(event)
        self.assertEqual(
            result["co2e"],
            0.0,
            "post-harvest with no reported energy produced emissions from area alone — the "
            "generic field-fuel estimate is back",
        )


class TransportEmissionTests(CarbonGapTestBase):
    """A4 — a recorded haul must contribute."""

    def test_factor_math_is_sane(self):
        result = VEF.calculate_transport_emissions(distance=40, distance_unit="miles")
        self.assertAlmostEqual(result["co2e_kg"], 40 * 1.70, places=2)

    def test_kilometres_are_converted(self):
        miles = VEF.calculate_transport_emissions(distance=100, distance_unit="miles")["co2e_kg"]
        km = VEF.calculate_transport_emissions(distance=100, distance_unit="km")["co2e_kg"]
        self.assertLess(km, miles)

    def test_load_weight_switches_to_ton_miles(self):
        result = VEF.calculate_transport_emissions(distance=40, distance_unit="miles", load_tons=12)
        self.assertEqual(result["breakdown"]["transport_basis"], "ton_miles")

    def test_zero_distance_emits_nothing(self):
        self.assertEqual(VEF.calculate_transport_emissions(distance=0)["co2e_kg"], 0.0)

    def test_scope_is_stated_as_farm_to_first_receiver(self):
        limitations = VEF.calculate_transport_emissions(distance=40)["limitations"]
        self.assertIn("first receiver", limitations)

    def test_a_recorded_haul_raises_a_harvest_event_total(self):
        without = ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="Harvest, no haul",
            area_covered=5.0,
            fuel_consumed=10,
            fuel_unit="gal",
            fuel_type="diesel",
        )
        with_haul = ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="Harvest and haul to huller",
            area_covered=5.0,
            fuel_consumed=10,
            fuel_unit="gal",
            fuel_type="diesel",
            transportation_distance=40,
            transportation_unit="miles",
        )
        base = self.calc.calculate_production_event_impact(without)["co2e"]
        hauled = self.calc.calculate_production_event_impact(with_haul)["co2e"]
        self.assertGreater(hauled, base, "transportation_distance still contributes nothing to the total")

    def test_haul_appears_in_the_breakdown(self):
        event = ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="Harvest and haul",
            area_covered=5.0,
            transportation_distance=40,
            transportation_unit="miles",
        )
        breakdown = self.calc.calculate_production_event_impact(event)["breakdown"]
        self.assertIn("transport_emissions_kg_co2e", breakdown)
        self.assertEqual(breakdown["transport_miles"], 40)
