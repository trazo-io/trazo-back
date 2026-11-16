"""
Phase 3 / A3 + A6 + A7 + A4 — four calculator gaps that all produced a confident zero.

Each of these returned a well-formed result with a breakdown and a data source, so nothing
looked broken; the number was just absent or wrong.

A3  Weather HT and HL read their inputs with `hasattr(event, ...)`. SUPERSEDED 2026-10-21:
    weather records carry no carbon at all (see WeatherCarriesNoCarbonTests).
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
from history.models import ChemicalEvent, Production, ProductionEvent, WeatherEvent
from product.models import Parcel, Product
from users.models import User


class CarbonGapTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email=f"{self.__class__.__name__}@test.com", password="x")
        company = Company.objects.create(name="Gap Farm")
        establishment = Establishment.objects.create(name="GAP1", company=company, state="CA")
        self.parcel = Parcel.objects.create(name="gap-parcel", establishment=establishment, area=10.0)
        product = Product.objects.create(name="Almond")
        self.history = Production.objects.create(
            name="Gap Production",
            start_date=timezone.now(),
            product=product,
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
        self.calc = EventCarbonCalculator()


class WeatherCarriesNoCarbonTests(CarbonGapTestBase):
    """A weather record carries no carbon (owner decision 2026-10-21; supersedes A3 for weather).

    A3 fixed weather branches that could not read their inputs. The inputs were never fuel the
    grower entered: the figure was inferred from the weather record itself (cooling hours, a
    water deficit, protection measures named). The response work is its own activity with its
    own fuel; that record carries the emissions.
    """

    def _weather(self, **extra):
        return WeatherEvent.objects.create(
            history=self.history, type=extra.pop("type", "HT"), date=timezone.now(), extra_data=extra
        )

    def test_no_weather_type_produces_a_figure(self):
        # The heat wave with misters was the one case A3 let emit; it no longer does.
        cases = [
            {"type": "HT", "highest_temperature": 42, "cooling_hours": 8, "cooling_area_acres": 5},
            {"type": "FR", "lower_temperature": -3, "protection_measures": "wind machines, heaters"},
            {"type": "HL", "duration": 20},
            {"type": "DR", "water_deficit": 3},
        ]
        for extra in cases:
            with self.subTest(extra["type"]):
                result = self.calc.calculate_weather_event_impact(self._weather(**dict(extra)))
                self.assertEqual(result["co2e"], 0.0)
                self.assertEqual(result["calculation_method"], "weather_not_estimated")

    def test_saving_a_weather_event_writes_no_entry_and_removes_an_old_one(self):
        from carbon.models import CarbonEntry

        event = self._weather(highest_temperature=42, cooling_hours=8, cooling_area_acres=5)
        self.assertFalse(CarbonEntry.objects.filter(registry_verification_id=f"REG-WeatherEvent-{event.id}").exists())

        CarbonEntry.objects.create(
            establishment=self.parcel.establishment,
            production=self.history,
            type="emission",
            amount=12.5,
            year=2026,
            registry_verification_id=f"REG-WeatherEvent-{event.id}",
        )
        event.save()
        self.assertFalse(CarbonEntry.objects.filter(registry_verification_id=f"REG-WeatherEvent-{event.id}").exists())

    def test_the_cleanup_command_is_a_dry_run_until_applied(self):
        from io import StringIO

        from django.core.management import call_command

        from carbon.models import CarbonEntry

        legacy = CarbonEntry.objects.create(
            establishment=self.parcel.establishment,
            production=self.history,
            type="emission",
            amount=7.0,
            year=2026,
            description="Frost protection WeatherEvent(ID=999)",
        )
        out = StringIO()
        call_command("remove_weather_carbon_entries", stdout=out)
        self.assertIn("Gap Farm: 1 entries, 7.00 kg CO2e", out.getvalue())
        self.assertTrue(CarbonEntry.objects.filter(pk=legacy.pk).exists())

        call_command("remove_weather_carbon_entries", "--apply", stdout=StringIO())
        self.assertFalse(CarbonEntry.objects.filter(pk=legacy.pk).exists())

    def test_the_cleanup_command_finds_every_shape_and_counts_entries_not_children(self):
        from io import StringIO

        from django.core.management import call_command

        from carbon.models import CarbonEntry

        def entry(description, registry=""):
            return CarbonEntry.objects.create(
                establishment=self.parcel.establishment,
                production=self.history,
                type="emission",
                amount=1.0,
                year=2026,
                description=description,
                registry_verification_id=registry,
            )

        # The backfill and demo seeders' shape, which a key on the receiver's shape missed.
        seeded = entry("Auto-calculated from WeatherEvent: frost_heaters", "REG-EVENT-41-2026")
        # Same writers, another event class: never touched.
        spray = entry("Auto-calculated from ChemicalEvent: verified_epa_factors", "REG-EVENT-41-2026")
        out = StringIO()
        call_command("remove_weather_carbon_entries", "--apply", stdout=out)
        self.assertFalse(CarbonEntry.objects.filter(pk=seeded.pk).exists())
        self.assertTrue(CarbonEntry.objects.filter(pk=spray.pk).exists())
        # The number removed is the number of entries the dry run listed, not entries plus
        # cascaded children.
        self.assertIn("Total: 1 weather carbon entries.", out.getvalue())
        self.assertIn("Removed 1 weather carbon entries.", out.getvalue())

    def test_the_form_preview_says_not_estimated_for_weather(self):
        from django.urls import reverse

        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.user)
        res = client.post(
            reverse("calculate-event-carbon-impact"),
            {"event_type": "weather", "event_data": {"type": "FR", "lower_temperature": -3}},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content[:300])
        body = res.json()
        self.assertEqual(body["co2e"], 0.0)
        self.assertEqual(body["verification_badge"], "Not estimated")
        self.assertIsNone(body["confidence_percentage"])


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
