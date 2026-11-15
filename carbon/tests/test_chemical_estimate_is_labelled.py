"""A spray or fertilizer figure says what it rests on, and invents no N-P-K or %AI (2026-11-13).

WHAT WAS WRONG
--------------
Found while fixing back #423 (no invented 50-unit amount):

* Every chemical figure was stored "epa_usda_verified", then stamped "factors_verified" with
  `usda_factors_based: True` and a blanket "USDA Agricultural Research Service" source by the
  metadata step, whatever it rested on. An application pass estimated from the area treated (a
  Trazo litres-per-hectare rate) therefore carried the same published-factor badge ("From recorded
  inputs") as a pass with recorded fuel, and so did a figure resting on a Trazo estimate factor
  (P2O5, K2O, copper, sulfur, organic products) or with its manufacturing left out. Summary
  records were stored "epa_usda_verified_aggregate" citing "USDA ARS (fertilizer manufacturing)".
  compliance.md: provenance is per input class, and an estimate is never presented as verified.
* The form preview (`calculate-event-carbon/`) and the legacy `calculate-event-impact/` priced a
  fertilizer with no N-P-K as 10-10-10; the save did the same when the analysis text held no three
  numbers.
* A spray with no concentration still carried a default %AI (25 to 99%) in its details with
  `concentration_source: "default"`, which the form printed as "25% (default)"; the summary
  preview printed an assumed 100%.

WHAT THIS PINS
--------------
* the status follows the basis: "factors_verified" (recorded quantities, published factors,
  nothing left out) or "estimate", stored, served, previewed and badged that way, with the reasons
  as codes and the fuel basis and per-factor provenance in the details;
* no N-P-K means no nutrient figure and a stated reason, on the save and both previews;
* no concentration means no active-ingredient figure, no printed percentage, and a stated reason.

It does not read the sibling repository.
"""

from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from rest_framework.test import APIClient

from carbon.event_link import entries_for_event
from carbon.services.calculator_service import CarbonCalculatorService
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.services.verified_emission_factors import (
    CHEMICAL_CONCENTRATION_NOT_RECORDED,
    CHEMICAL_ESTIMATE_REASONS,
    CHEMICAL_NPK_NOT_RECORDED,
    CHEMICAL_PASS_ESTIMATED_FROM_AREA,
    PROVENANCE_INTERNAL_ESTIMATE,
    PROVENANCE_PUBLISHED,
    VerifiedEmissionFactors,
)
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from history.serializers import ChemicalEventSerializer
from history.services.audit_export_service import _emission_factor_basis
from history.services.records_export import _factor_basis
from product.models import Parcel, Product
from users.models import User, WorksIn

FACTORS = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS


# The form preview caches each answer for five minutes under a hash of the request. Against a
# shared cache, a run would read the answer a previous run (or the code before a change) wrote.
@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class _Block(TestCase):
    """A fictional Washington apple block with one open season."""

    def setUp(self):
        self.user = User.objects.create_user(email="estimate-label@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Fictional Ridge Orchard")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Fictional Ridge", company=self.company, state="WA")
        self.history = Production.objects.create(
            name="Gala 2026",
            parcel=Parcel.objects.create(name="South Block", establishment=est, area=4.0),
            product=Product.objects.create(name="Apples"),
            operator=self.user,
            start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _record(self, **extra):
        """A synthetic fungicide weighed out in pounds, with its concentration, on a known area."""
        values = dict(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            date=datetime(2026, 5, 2, 7, 15, tzinfo=dt_tz.utc),
            commercial_name="Fictional Captan 80",
            chemical_subtype="",
            concentration="80%",
            volume_numeric=Decimal("5"),
            volume_unit="lbs",
            area_numeric=Decimal("4"),
            area_unit="acres",
            way_of_application="air_blast",
        )
        values.update(extra)
        return ChemicalEvent.objects.create(**values)

    def _stored(self, record):
        entries = list(entries_for_event(record, link=False))
        self.assertEqual(len(entries), 1, "expected one stored carbon entry")
        return entries[0]

    def _served(self, record):
        return ChemicalEventSerializer(record).data["carbon_data"]

    def _preview(self, event_data):
        response = self.client.post(
            reverse("calculate-event-carbon"), {"event_type": "chemical", "event_data": event_data}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def _legacy(self, event_data):
        response = self.client.post(
            reverse("calculate-event-carbon-impact"),
            {"event_type": "chemical", "event_data": event_data},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def assertIsAnEstimate(self, status, breakdown, reason):
        self.assertEqual(status, "estimate")
        self.assertEqual(breakdown["figure_basis"], "estimate")
        self.assertIn(reason, breakdown["estimate_reasons"])


class AreaEstimatedPassTests(_Block):
    """No fuel on the record, an area: the pass is a Trazo per-hectare estimate."""

    def test_the_stored_entry_is_an_estimate_and_carries_no_published_flag(self):
        record = self._record()
        entry = self._stored(record)
        self.assertIsAnEstimate(entry.verification_status, entry.baseline_data, "application_fuel_estimated_from_area")
        self.assertFalse(entry.usda_factors_based)
        self.assertNotIn("verified", entry.description)
        self.assertNotIn("USDA", entry.data_source)
        fuel_basis = entry.baseline_data["fuel_basis"]
        self.assertFalse(fuel_basis["measured"])
        self.assertEqual(fuel_basis["estimated_from"], "area_and_application_method")
        self.assertEqual(fuel_basis["assumed_rate"]["value"], 4.0)
        self.assertEqual(fuel_basis["assumed_rate"]["unit"], "L/ha")
        self.assertEqual(fuel_basis["assumed_rate"]["provenance"], PROVENANCE_INTERNAL_ESTIMATE)
        # Each factor applied is listed with its own source, and the fuel line says its quantity
        # was estimated, not recorded.
        by_component = {line["component"]: line for line in entry.baseline_data["component_provenance"]}
        self.assertEqual(by_component["application_fuel"]["quantity"], "estimated_from_area")
        self.assertEqual(by_component["product"]["source"], FACTORS["fungicide_manufacturing"].source)
        self.assertEqual(by_component["product"]["quantity"], "recorded_mass")
        # And the limitation says it in words.
        result = EventCarbonCalculator().calculate_chemical_event_impact(record)
        self.assertIn(CHEMICAL_PASS_ESTIMATED_FROM_AREA, result["limitations"])

    def test_the_served_payload_says_estimate_with_its_reasons(self):
        served = self._served(self._record())
        self.assertEqual(served["verification_status"], "estimate")
        self.assertEqual(served["calculation_basis"], "estimate")
        self.assertFalse(served["usda_factors_based"])
        self.assertIn("application_fuel_estimated_from_area", served["estimate_reasons"])

    def test_no_consumer_total_counts_it(self):
        self.assertNotIn("estimate", CarbonCalculatorService.RECORDED_BASIS_STATUSES)
        self._record()
        result = CarbonCalculatorService().calculate_production_carbon(self.history.id)
        self.assertGreater(result["total_emissions"], 0)
        self.assertEqual(result["recorded_emissions"], 0)

    def test_the_form_preview_labels_it_an_estimate(self):
        payload = self._preview(
            {
                "type": "FU",
                "commercial_name": "Fictional Captan 80",
                "concentration": "80",
                "volume_applied": "5",
                "volume_unit": "lbs",
                "area_treated": "4",
                "area_unit": "acres",
                "application_method": "air_blast",
            }
        )
        self.assertIsAnEstimate(
            payload["verification_status"], payload["breakdown"], "application_fuel_estimated_from_area"
        )
        self.assertFalse(payload["breakdown"]["fuel_basis"]["measured"])
        self.assertNotIn("verified", payload["calculation_method"])

    def test_the_legacy_endpoint_badges_it_an_estimate(self):
        payload = self._legacy(
            {
                "type": "FU",
                "commercial_name": "Fictional Captan 80",
                "concentration": "80",
                "volume": "5",
                "volume_unit": "lbs",
                "area": "4",
                "area_unit": "acres",
                "way_of_application": "air_blast",
            }
        )
        self.assertEqual(payload["verification_status"], "estimate")
        self.assertEqual(payload["verification_badge"], "Estimate")
        self.assertEqual(payload["verification_level"], "estimate")
        self.assertFalse(payload["usda_factors_based"])
        self.assertNotIn("USDA", payload["data_source"])
        self.assertNotIn("usda_compliance", payload)

    def test_the_records_export_and_the_audit_pdf_word_it_as_an_estimate(self):
        for text in (_factor_basis("estimate"), _emission_factor_basis("estimate")):
            self.assertTrue(text.startswith("Estimate"), text)
            self.assertNotIn("verified", text.lower())
            self.assertNotIn("Published factor", text)


class RecordedFuelTests(_Block):
    """Recorded diesel, a published product factor on a recorded mass: nothing estimated."""

    def _fuelled(self, **extra):
        return self._record(
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("2"),
            application_fuel_unit="gal",
            **extra,
        )

    def test_it_keeps_its_published_provenance_named_per_input(self):
        record = self._fuelled()
        result = EventCarbonCalculator().calculate_chemical_event_impact(record)
        self.assertEqual(result["verification_status"], "factors_verified")
        self.assertEqual(result["breakdown"]["figure_basis"], "published_factors")
        self.assertEqual(result["breakdown"]["estimate_reasons"], [])
        self.assertTrue(result["breakdown"]["fuel_basis"]["measured"])
        self.assertIsNone(result["breakdown"]["fuel_basis"]["assumed_rate"])
        lines = result["breakdown"]["component_provenance"]
        self.assertEqual(
            {(line["component"], line["factor"], line["provenance"], line["quantity"]) for line in lines},
            {
                ("product", "fungicide_manufacturing", PROVENANCE_PUBLISHED, "recorded_mass"),
                ("application_fuel", "application_fuel", PROVENANCE_PUBLISHED, "recorded_fuel"),
            },
        )
        # The source column names the two factors applied, not a blanket agency.
        self.assertEqual(
            result["data_source"],
            f"{FACTORS['fungicide_manufacturing'].source}; {FACTORS['application_fuel'].source}",
        )

    def test_stored_and_served_as_from_recorded_inputs(self):
        record = self._fuelled()
        entry = self._stored(record)
        self.assertEqual(entry.verification_status, "factors_verified")
        self.assertTrue(entry.usda_factors_based)
        served = self._served(record)
        self.assertEqual(served["verification_status"], "epa_usda_sourced")
        self.assertTrue(served["usda_factors_based"])
        self.assertEqual(served["estimate_reasons"], [])

    def test_a_trazo_estimate_factor_makes_it_an_estimate_even_with_recorded_fuel(self):
        # Copper is a Trazo estimate (PROVENANCE_INTERNAL_ESTIMATE), whatever else was recorded.
        record = self._fuelled(commercial_name="Kocide 3000-O", chemical_subtype="copper_fungicide")
        entry = self._stored(record)
        self.assertIsAnEstimate(entry.verification_status, entry.baseline_data, "trazo_estimate_factor")
        self.assertFalse(entry.usda_factors_based)

    def test_a_volume_turned_into_weight_by_a_typical_density_is_an_estimate(self):
        record = self._fuelled(volume_numeric=Decimal("2"), volume_unit="gal")
        entry = self._stored(record)
        self.assertIsAnEstimate(entry.verification_status, entry.baseline_data, "product_mass_from_typical_density")

    def test_a_left_out_part_makes_it_an_estimate(self):
        record = self._fuelled(concentration="")
        entry = self._stored(record)
        self.assertIsAnEstimate(entry.verification_status, entry.baseline_data, "concentration_not_recorded")


class FertilizerWithNoNpkTests(_Block):
    def _fertilizer(self, **extra):
        values = dict(
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Fictional Orchard Blend",
            concentration="",
            volume_numeric=Decimal("200"),
            volume_unit="lbs",
            way_of_application="broadcast",
        )
        values.update(extra)
        return self._record(**values)

    def assertNoNutrientFigure(self, breakdown):
        self.assertEqual(breakdown["manufacturing_emissions_kg_co2e"], 0)
        self.assertEqual(breakdown.get("nitrogen_kg", 0), 0)
        self.assertTrue(breakdown["manufacturing_emissions_omitted"])
        self.assertEqual(breakdown["manufacturing_omitted_code"], "npk_not_recorded")
        self.assertEqual(breakdown["manufacturing_omitted_reason"], CHEMICAL_NPK_NOT_RECORDED)
        self.assertIn("npk_not_recorded", breakdown["estimate_reasons"])
        self.assertNotIn({"N": 10.0, "P": 10.0, "K": 10.0}, [breakdown.get("npk_content")])

    def test_the_save_states_the_missing_analysis_and_cites_no_nutrient_factor(self):
        record = self._fertilizer()
        result = EventCarbonCalculator().calculate_chemical_event_impact(record)
        self.assertNoNutrientFigure(result["breakdown"])
        self.assertIn(CHEMICAL_NPK_NOT_RECORDED, result["limitations"])
        for nutrient in ("nitrogen_fertilizer", "phosphorus_fertilizer", "potassium_fertilizer"):
            self.assertNotIn(FACTORS[nutrient].source, result["data_sources"])
        self.assertEqual(self._stored(record).verification_status, "estimate")

    def test_analysis_text_with_no_three_numbers_is_no_analysis(self):
        # "compost tea" was read as 10-10-10.
        self.assertEqual(
            EventCarbonCalculator()._parse_npk_content("compost tea", "FE"), {"N": 0.0, "P": 0.0, "K": 0.0}
        )
        result = EventCarbonCalculator().calculate_chemical_event_impact(self._fertilizer(concentration="compost tea"))
        self.assertNoNutrientFigure(result["breakdown"])

    def test_the_form_preview_invents_no_npk(self):
        payload = self._preview(
            {
                "type": "FE",
                "commercial_name": "Fictional Orchard Blend",
                "volume_applied": "200",
                "volume_unit": "lbs",
                "area_treated": "4",
                "area_unit": "acres",
                "application_method": "broadcast",
            }
        )
        self.assertNoNutrientFigure(payload["breakdown"])
        self.assertEqual(payload["npk_content"], {"N": 0, "P": 0, "K": 0})
        self.assertEqual(payload["verification_status"], "estimate")

    def test_the_form_preview_reads_the_three_percentage_fields(self):
        payload = self._preview(
            {
                "type": "FE",
                "volume_applied": "200",
                "volume_unit": "lbs",
                "nitrogen_percentage": "20",
                "phosphorus_percentage": "0",
                "potassium_percentage": "0",
                "area_treated": "4",
                "area_unit": "acres",
                "application_method": "broadcast",
            }
        )
        self.assertAlmostEqual(payload["breakdown"]["nitrogen_kg"], 200 * 0.45359237 * 0.20, places=3)
        self.assertNotIn("manufacturing_emissions_omitted", payload["breakdown"])

    def test_the_preview_reads_the_percentage_fields_before_the_ratio_text(self):
        # Review of back #426: with "46% N" typed and N 46 / P 0 / K 0 filled, the save prices the urea
        # from the fields (`_get_structured_npk_content`); the preview read the text first, which has
        # no "-" ratio, and showed no nutrient figure. Same input, same answer as the save.
        payload = self._preview(
            {
                "type": "FE",
                "concentration": "46% N",
                "volume_applied": "200",
                "volume_unit": "lbs",
                "nitrogen_percentage": "46",
                "phosphorus_percentage": "0",
                "potassium_percentage": "0",
                "area_treated": "4",
                "area_unit": "acres",
                "application_method": "broadcast",
            }
        )
        self.assertAlmostEqual(payload["breakdown"]["nitrogen_kg"], 200 * 0.45359237 * 0.46, places=3)
        self.assertNotIn("manufacturing_emissions_omitted", payload["breakdown"])

    def test_the_legacy_endpoint_invents_no_npk(self):
        payload = self._legacy(
            {
                "type": "FE",
                "commercial_name": "Fictional Orchard Blend",
                "volume": "200",
                "volume_unit": "lbs",
                "area": "4",
                "area_unit": "acres",
                "way_of_application": "broadcast",
            }
        )
        self.assertNoNutrientFigure(payload["breakdown"])
        self.assertEqual(payload["verification_badge"], "Estimate")

    def test_an_organic_fertilizer_keeps_its_processing_figure_and_states_the_missing_nitrogen(self):
        record = self._fertilizer(chemical_subtype="organic_fertilizer")
        breakdown = EventCarbonCalculator().calculate_chemical_event_impact(record)["breakdown"]
        processing = FACTORS["organic_fertilizer_manufacturing"].value * 200 * 0.45359237
        self.assertAlmostEqual(breakdown["manufacturing_emissions_kg_co2e"], processing, places=2)
        self.assertNotIn("manufacturing_emissions_omitted", breakdown)
        self.assertIn("nitrogen_not_recorded", breakdown["estimate_reasons"])
        self.assertEqual(breakdown["field_n2o_emissions_kg_co2e"], 0)
        self.assertNotIn("nitrogen_field_n2o", [line["factor"] for line in breakdown["component_provenance"]])


class SprayWithNoConcentrationTests(_Block):
    def assertNoActiveIngredientFigure(self, breakdown):
        self.assertNotIn("active_ingredient_percentage", breakdown)
        self.assertNotIn("active_ingredient_kg", breakdown)
        self.assertEqual(breakdown["concentration_source"], "not_recorded")
        self.assertEqual(breakdown["manufacturing_emissions_kg_co2e"], 0)
        self.assertEqual(breakdown["manufacturing_omitted_code"], "concentration_not_recorded")
        self.assertEqual(breakdown["manufacturing_omitted_reason"], CHEMICAL_CONCENTRATION_NOT_RECORDED)
        self.assertIn("concentration_not_recorded", breakdown["estimate_reasons"])

    def test_no_subtype_prints_a_default_percentage(self):
        subtypes = {
            "PE": ["", "organic_pesticide", "biological_pesticide"],
            "HE": ["", "organic_herbicide"],
            "FU": ["", "copper_fungicide", "sulfur_fungicide", "biological_fungicide", "organic_fungicide"],
        }
        for chemical_type, names in subtypes.items():
            for subtype in names:
                with self.subTest(chemical_type=chemical_type, subtype=subtype):
                    result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
                        chemical_type=chemical_type,
                        volume_liters=0.0,
                        chemical_mass_kg=3.0,
                        area_hectares=1.0,
                        npk_content={"N": 0, "P": 0, "K": 0},
                        chemical_subtype=subtype,
                    )
                    self.assertNoActiveIngredientFigure(result["breakdown"])
                    self.assertIn(CHEMICAL_CONCENTRATION_NOT_RECORDED, result["limitations"])

    def test_the_save_and_the_preview_print_no_percentage(self):
        record = self._record(concentration="")
        self.assertNoActiveIngredientFigure(
            EventCarbonCalculator().calculate_chemical_event_impact(record)["breakdown"]
        )
        payload = self._preview(
            {
                "type": "FU",
                "volume_applied": "5",
                "volume_unit": "lbs",
                "area_treated": "4",
                "area_unit": "acres",
                "application_method": "air_blast",
            }
        )
        self.assertNoActiveIngredientFigure(payload["breakdown"])

    def test_a_zero_built_from_left_out_parts_is_not_estimated_in_the_preview(self):
        # No concentration, no fuel, no area: nothing to count, and the form must not read the
        # zero as "no emissions to estimate".
        payload = self._preview({"type": "FU", "volume_applied": "5", "volume_unit": "lbs"})
        self.assertEqual(payload["co2e"], 0)
        self.assertTrue(payload["not_estimated"])
        self.assertEqual(
            payload["breakdown"]["estimate_reasons"], ["concentration_not_recorded", "application_not_estimated"]
        )
        # A figure is still a figure.
        self.assertFalse(
            self._preview(
                {"type": "FU", "volume_applied": "5", "volume_unit": "lbs", "area_treated": "4", "area_unit": "acres"}
            )["not_estimated"]
        )

    def test_the_summary_preview_prints_no_assumed_100_percent(self):
        payload = self._preview(
            {
                "type": "PE",
                "is_summary": "true",
                "event_count": 3,
                "active_ingredient_total_kg": "1.5",
                "fuel_consumption_total": "4",
                "application_fuel_type": "diesel",
                "application_fuel_unit": "gal",
            }
        )
        self.assertIsNone(payload["breakdown"]["active_ingredient_percentage"])
        self.assertEqual(payload["breakdown"]["active_ingredient_kg"], 1.5)
        # Synthetic pesticide factor is published and the fuel was recorded: nothing estimated.
        self.assertEqual(payload["breakdown"]["figure_basis"], "published_factors")


class SummaryRecordTests(_Block):
    def _summary(self, chemical_type, **extra_data):
        data = {"is_summary": True, "event_count": 4, "fuel_type": "diesel", "fuel_unit": "gal"}
        data.update(extra_data)
        return self._record(type=chemical_type, volume_numeric=None, extra_data=data)

    def test_recorded_totals_and_fuel_with_published_factors_keep_the_aggregate_status(self):
        entry = self._stored(
            self._summary(ChemicalEvent.PESTICIDE, active_ingredient_total_kg=1.2, fuel_consumption_total=6)
        )
        self.assertEqual(entry.verification_status, "epa_usda_verified_aggregate")
        self.assertEqual(entry.baseline_data["figure_basis"], "published_factors")

    def test_a_trazo_estimate_factor_or_no_fuel_makes_a_summary_an_estimate(self):
        copper = self._stored(
            self._summary(
                ChemicalEvent.FUNGICIDE,
                active_ingredient_total_kg=2.0,
                fuel_consumption_total=6,
                chemical_subtype="copper_fungicide",
            )
        )
        self.assertIsAnEstimate(copper.verification_status, copper.baseline_data, "trazo_estimate_factor")
        self.assertFalse(copper.usda_factors_based)
        no_fuel = EventCarbonCalculator().calculate_chemical_event_impact(
            self._summary(ChemicalEvent.PESTICIDE, active_ingredient_total_kg=1.2)
        )
        self.assertIsAnEstimate(no_fuel["verification_status"], no_fuel["breakdown"], "application_not_estimated")

    def test_a_fertilizer_summary_cites_the_registry_sources_not_usda(self):
        result = EventCarbonCalculator().calculate_chemical_event_impact(
            self._summary(
                ChemicalEvent.FERTILIZER, n_total_kg=40, p_total_kg=10, k_total_kg=0, fuel_consumption_total=5
            )
        )
        self.assertNotIn("USDA ARS (fertilizer manufacturing)", result["data_sources"])
        self.assertIn(FACTORS["nitrogen_fertilizer"].source, result["data_sources"])
        self.assertIn(FACTORS["phosphorus_fertilizer"].source, result["data_sources"])
        # P2O5 is a Trazo estimate.
        self.assertIsAnEstimate(result["verification_status"], result["breakdown"], "trazo_estimate_factor")


class ReasonsAreWordedTests(TestCase):
    def test_every_reason_code_has_a_sentence_with_no_em_dash_and_no_verified(self):
        for code, sentence in CHEMICAL_ESTIMATE_REASONS.items():
            with self.subTest(code=code):
                self.assertTrue(sentence)
                self.assertNotIn("\u2014", sentence)
                self.assertNotIn("verified", sentence.lower())
