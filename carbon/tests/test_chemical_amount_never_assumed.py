"""A spray or fertilizer record with no amount gets no invented amount (tank-mix review 2026-11-12).

WHAT WAS WRONG
--------------
`EventCarbonCalculator._extract_chemical_event_data` read a record with no `volume_numeric` and a
blank `volume` as `getattr(event, "volume_applied", "50")`, falling back to 50.0, so a spray whose
source record gives no amount was priced on 50 units nobody recorded. The same function read a
missing area as `area_treated` "1.0" (one hectare), a legacy free-text amount with no number in it
("Unknown") as a per-crop default of 10 to 75 L, and the legacy `calculate-event-impact/` stand-in
supplied "10" L and "1.0" ha. Meanwhile `calculate_chemical_application_emissions` voided the
whole result when the amount OR the area was missing, recorded fuel included, so the form preview
(which passes 0 for a blank) showed nothing where the save showed a figure built on 50.

WHAT THIS PINS
--------------
Unknown is not a number (memory: feedback-prod-data-ops-and-unknowns, demo-data-numbers rule):

* no amount: no manufacturing figure, the breakdown and the limitations say why, and no 50 (or
  any other stand-in amount) appears anywhere in the details;
* the application pass is computed from what it needs: recorded fuel always counts; the
  per-hectare estimate needs the area treated, and says it is an estimate from the area; with
  neither, the pass is not estimated, stated, and nothing is stored;
* an amount with no area keeps its manufacturing figure and charges no pass on an invented hectare;
* a fertilizer is treated the same way; the preview matches the save; the legacy stand-in sends
  no default amount.

It does not read the sibling repository.
"""

from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from rest_framework.test import APIClient

from carbon.event_link import entries_for_event
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.services.verified_emission_factors import (
    CHEMICAL_AMOUNT_NOT_RECORDED,
    CHEMICAL_PASS_ESTIMATED_FROM_AREA,
    CHEMICAL_PASS_NOT_ESTIMATED,
    VerifiedEmissionFactors,
)
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel, Product
from users.models import User, WorksIn

ACRE_HA = 0.404686
AIR_BLAST_L_PER_HA = 4.0
BROADCAST_L_PER_HA = 0.8
L_PER_GAL = 3.78541


def _numbers(value):
    """Every number in a payload, however deeply nested."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float, Decimal)):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _numbers(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _numbers(item)


def _pass_estimate_kg(acres, litres_per_ha):
    fuel_factor = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["application_fuel"].value
    return acres * ACRE_HA * litres_per_ha / L_PER_GAL * fuel_factor


class _Block(TestCase):
    """A fictional Washington block with one open season."""

    def setUp(self):
        self.user = User.objects.create_user(email="no-amount@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Fictional Bench Orchard")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Fictional Bench", company=self.company, state="WA")
        self.history = Production.objects.create(
            name="Honeycrisp 2026",
            parcel=Parcel.objects.create(name="North Block", establishment=est, area=4.0),
            product=Product.objects.create(name="Apples"),
            operator=self.user,
            start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
        )

    def _record(self, **extra):
        """A copper spray keyed in from a paper log that shows the product but no amount."""
        values = dict(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            date=datetime(2026, 4, 20, 9, 30, tzinfo=dt_tz.utc),
            commercial_name="Kocide 3000-O",
            chemical_subtype="copper_fungicide",
            concentration="30%",
            area_numeric=Decimal("4"),
            area_unit="acres",
            way_of_application="air_blast",
        )
        values.update(extra)
        return ChemicalEvent.objects.create(**values)

    def _calculate(self, record):
        return EventCarbonCalculator().calculate_chemical_event_impact(record)

    def _stored(self, record):
        return list(entries_for_event(record, link=False))

    def assertNoStandInAmount(self, breakdown):
        self.assertEqual(breakdown["volume_applied_liters"], 0)
        self.assertEqual(breakdown["chemical_mass_kg"], 0)
        self.assertEqual(breakdown.get("active_ingredient_kg", 0), 0)
        self.assertEqual(breakdown["manufacturing_emissions_kg_co2e"], 0)
        self.assertNotIn(50.0, list(_numbers(breakdown)), "a stand-in amount of 50 is back in the details")


class NoAmountTests(_Block):
    def test_no_manufacturing_figure_and_the_details_say_why(self):
        result = self._calculate(self._record())
        breakdown = result["breakdown"]
        self.assertNoStandInAmount(breakdown)
        self.assertTrue(breakdown["manufacturing_emissions_omitted"])
        self.assertEqual(breakdown["manufacturing_omitted_reason"], CHEMICAL_AMOUNT_NOT_RECORDED)
        self.assertIn(CHEMICAL_AMOUNT_NOT_RECORDED, result["limitations"])
        # No product term ran, so no product factor is cited.
        copper = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["copper_fungicide_manufacturing"]
        self.assertNotIn(copper.source, result["data_sources"])

    def test_with_the_area_known_the_pass_is_an_area_estimate_and_says_so(self):
        record = self._record()
        result = self._calculate(record)
        breakdown = result["breakdown"]
        expected = _pass_estimate_kg(4, AIR_BLAST_L_PER_HA)
        self.assertAlmostEqual(breakdown["application_emissions_kg_co2e"], expected, places=2)
        self.assertAlmostEqual(result["co2e"], expected, places=2)
        self.assertEqual(breakdown["application_pass_basis"], "estimated_application_fuel")
        self.assertEqual(breakdown["application_pass_note"], CHEMICAL_PASS_ESTIMATED_FROM_AREA)
        self.assertIn(CHEMICAL_PASS_ESTIMATED_FROM_AREA, result["limitations"])
        # The save stores that figure and nothing built on an amount.
        stored = self._stored(record)
        self.assertEqual(len(stored), 1)
        self.assertAlmostEqual(float(stored[0].co2e_amount), expected, places=2)
        self.assertNoStandInAmount(stored[0].baseline_data)

    def test_with_the_area_blank_too_nothing_is_estimated_or_stored(self):
        record = self._record(area_numeric=None)
        result = self._calculate(record)
        breakdown = result["breakdown"]
        self.assertEqual(result["co2e"], 0)
        self.assertNoStandInAmount(breakdown)
        self.assertEqual(breakdown["area_treated_hectares"], 0)
        self.assertEqual(breakdown["application_emissions_kg_co2e"], 0)
        self.assertEqual(breakdown["application_pass_basis"], "application_not_estimated")
        self.assertEqual(breakdown["application_pass_note"], CHEMICAL_PASS_NOT_ESTIMATED)
        self.assertIn(CHEMICAL_AMOUNT_NOT_RECORDED, result["limitations"])
        self.assertIn(CHEMICAL_PASS_NOT_ESTIMATED, result["limitations"])
        self.assertEqual(result["data_sources"], [])
        self.assertEqual(self._stored(record), [])

    def test_recorded_fuel_counts_with_neither_amount_nor_area(self):
        record = self._record(
            area_numeric=None,
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("3"),
            application_fuel_unit="gal",
        )
        breakdown = self._calculate(record)["breakdown"]
        fuel_factor = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["application_fuel"].value
        self.assertAlmostEqual(breakdown["application_emissions_kg_co2e"], 3 * fuel_factor, places=2)
        self.assertEqual(breakdown["application_pass_basis"], "actual_application_fuel")
        self.assertNotIn("application_pass_note", breakdown)
        self.assertNoStandInAmount(breakdown)
        self.assertTrue(breakdown["manufacturing_emissions_omitted"])

    def test_a_legacy_free_text_amount_with_no_number_is_no_amount(self):
        # "Unknown" read as a per-crop default of 20 L for a fungicide.
        record = self._record(volume="Unknown", volume_unit="L")
        self.assertEqual(EventCarbonCalculator()._extract_chemical_event_data(record)["volume_liters"], 0.0)
        breakdown = self._calculate(record)["breakdown"]
        self.assertNoStandInAmount(breakdown)
        self.assertEqual(breakdown["manufacturing_omitted_reason"], CHEMICAL_AMOUNT_NOT_RECORDED)

    def test_a_fertilizer_with_no_amount_is_treated_the_same(self):
        record = self._record(
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Fictional 46-0-0",
            chemical_subtype="",
            concentration="46-0-0",
            way_of_application="broadcast",
        )
        result = self._calculate(record)
        breakdown = result["breakdown"]
        self.assertNoStandInAmount(breakdown)
        self.assertEqual(breakdown["nitrogen_kg"], 0)
        self.assertEqual(breakdown["manufacturing_omitted_reason"], CHEMICAL_AMOUNT_NOT_RECORDED)
        self.assertAlmostEqual(
            breakdown["application_emissions_kg_co2e"], _pass_estimate_kg(4, BROADCAST_L_PER_HA), places=2
        )
        nitrogen = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["nitrogen_fertilizer"]
        self.assertNotIn(nitrogen.source, result["data_sources"])


class AmountWithoutAreaTests(_Block):
    def test_the_manufacturing_figure_stays_and_no_hectare_is_invented(self):
        # A missing area read as `area_treated` "1.0": one hectare of pass the record never names.
        record = self._record(area_numeric=None, volume_numeric=Decimal("8"), volume_unit="lbs")
        breakdown = self._calculate(record)["breakdown"]
        copper = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["copper_fungicide_manufacturing"].value
        expected = 8 * 0.45359237 * 0.30 * copper
        self.assertAlmostEqual(breakdown["manufacturing_emissions_kg_co2e"], expected, places=2)
        self.assertNotIn("manufacturing_emissions_omitted", breakdown)
        self.assertEqual(breakdown["area_treated_hectares"], 0)
        self.assertEqual(breakdown["application_emissions_kg_co2e"], 0)
        self.assertEqual(breakdown["application_pass_basis"], "application_not_estimated")
        self.assertEqual(breakdown["application_pass_note"], CHEMICAL_PASS_NOT_ESTIMATED)


class PreviewAndLegacyStandInTests(_Block):
    def test_the_preview_matches_what_the_save_computes(self):
        from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor

        saved = self._calculate(self._record())["breakdown"]
        processed = OptimizedEventProcessor._process_chemical_event(
            {
                "type": "FU",
                "commercial_name": "Kocide 3000-O",
                "chemical_subtype": "copper_fungicide",
                "concentration": "30",
                "area_numeric": "4",
                "area_unit": "acres",
                "application_method": "air_blast",
            }
        )
        preview = OptimizedCarbonCalculator().calculate_chemical_impact_optimized(processed)["breakdown"]
        self.assertTrue(preview["manufacturing_emissions_omitted"])
        self.assertEqual(preview["manufacturing_omitted_reason"], CHEMICAL_AMOUNT_NOT_RECORDED)
        self.assertAlmostEqual(
            preview["application_emissions_kg_co2e"], saved["application_emissions_kg_co2e"], places=3
        )

    def test_the_legacy_stand_in_sends_no_default_amount(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post(
            reverse("calculate-event-carbon-impact"),
            {
                "event_type": "chemical",
                "event_data": {
                    "type": "FU",
                    "commercial_name": "Kocide 3000-O",
                    "chemical_subtype": "copper_fungicide",
                    "concentration": "30",
                    "area": "4",
                    "area_unit": "acres",
                    "way_of_application": "air_blast",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        breakdown = response.json()["breakdown"]
        self.assertNoStandInAmount(breakdown)
        self.assertEqual(breakdown["manufacturing_omitted_reason"], CHEMICAL_AMOUNT_NOT_RECORDED)
