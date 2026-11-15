"""Carbon figures and wording say only what the entries establish (2026-11-05 audit).

Each test pins one defect the CarbonEntry audit found live on origin/main:

- a zero result stored as an "offset", so summaries counted it as one;
- blanket provenance written into every entry ("using USDA emission factors", "USDA_<CLASS>",
  "verified farm event data") and shipped in the farmer's records export;
- carbon sources named by event code alone, so a pest beneficial release ("BR") was filed under
  "Equipment Breakdown";
- the retired carbon score still served on the history list;
- the LATEST SINGLE entry presented as a season's footprint on consumer surfaces;
- a season with no entries borrowing every entry of the same farm and year.
"""

import io
import zipfile
from importlib import import_module

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from carbon.models import CarbonEntry
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from company.models import Company, Establishment
from history.models import EquipmentEvent, PestManagementEvent, Production
from history.serializers import OptimizedHistoryListSerializer
from history.serializers_consumer import season_recorded_emissions
from history.services.records_export import export_establishment_records_zip
from product.models import Parcel

RECORDED = "factors_verified"


class _Farm(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Carbon Co")
        self.est = Establishment.objects.create(name="Carbon Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=self.est, area=1)
        self.history = Production.objects.create(parcel=parcel, name="2026", start_date=timezone.now())

    def _pest(self, code="BR"):
        return PestManagementEvent.objects.create(
            history=self.history, type=code, description="pest", date=timezone.now()
        )

    def _entry(self, co2e, **kw):
        defaults = dict(
            production=self.history,
            establishment=self.est,
            type="emission",
            amount=abs(co2e),
            co2e_amount=co2e,
            year=timezone.now().year,
            verification_status=RECORDED,
        )
        defaults.update(kw)
        return CarbonEntry.objects.create(**defaults)


class EntriesWrittenFromEventsTests(_Farm):
    def _write(self, event, co2e):
        CarbonEntry.objects.filter(production=self.history).delete()
        return EventCarbonCalculator().create_carbon_entry_from_event(
            event, {"co2e": co2e, "verification_status": RECORDED, "data_source": "test"}
        )

    def test_a_zero_is_an_emission_of_zero_and_only_a_negative_is_an_offset(self):
        event = self._pest("SC")
        self.assertEqual(self._write(event, 0).type, "emission")
        self.assertEqual(self._write(event, -2.5).type, "offset")
        self.assertEqual(self._write(event, 3.0).type, "emission")

    def test_no_blanket_provenance_is_written(self):
        entry = self._write(self._pest("SC"), 1.0)
        self.assertEqual((entry.methodology_template, entry.permanence_plan), ("", ""))

    def test_sources_are_named_by_kind_and_code(self):
        self.assertEqual(self._write(self._pest("BR"), 1.0).source.name, "Beneficial Release")
        breakdown = EquipmentEvent.objects.create(
            history=self.history, type="BD", description="broke", date=timezone.now()
        )
        self.assertEqual(self._write(breakdown, 1.0).source.name, "Equipment Breakdown")
        maintenance = EquipmentEvent.objects.create(
            history=self.history, type="MN", description="service", date=timezone.now()
        )
        self.assertEqual(self._write(maintenance, 1.0).source.name, "Equipment Maintenance")


class RelabelMigrationTests(_Farm):
    def test_existing_zero_offsets_become_emissions_and_reverse_exactly(self):
        zero = self._entry(0, type="offset", amount=0)
        real_offset = self._entry(-4, type="offset")
        # What the offset endpoints write: `amount` set, `co2e_amount` left at its default of 0
        # (review of back #308: the first predicate relabelled these as emissions).
        user_offset = self._entry(0, type="offset", amount=500)
        migration = import_module("carbon.migrations.0045_zero_is_not_an_offset")
        migration.relabel(apps, None)
        for row in (zero, real_offset, user_offset):
            row.refresh_from_db()
        self.assertEqual((zero.type, real_offset.type, user_offset.type), ("emission", "offset", "offset"))
        migration.restore(apps, None)
        zero.refresh_from_db()
        user_offset.refresh_from_db()
        self.assertEqual((zero.type, user_offset.type), ("offset", "offset"))


class SurfacesTests(_Farm):
    def test_the_history_list_serves_no_carbon_score(self):
        self._entry(5)
        data = OptimizedHistoryListSerializer(self.history).data
        self.assertNotIn("carbon_score", data.get("extra_data") or {})

    def test_a_consumer_surface_states_the_season_total_not_one_row(self):
        self._entry(5)
        self._entry(7)
        self.assertEqual(season_recorded_emissions(self.history.pk), 12.0)

    def test_a_season_without_carbon_data_states_none(self):
        self.assertIsNone(season_recorded_emissions(self.history.pk))

    def test_a_season_with_no_entries_does_not_borrow_its_farms(self):
        """complete_summary added every same-year entry of the farm to an empty season."""
        other = Production.objects.create(parcel=self.history.parcel, name="other", start_date=timezone.now())
        self._entry(40, production=other)
        from carbon.views import PublicProductionViewSet

        source = __import__("inspect").getsource(PublicProductionViewSet.complete_summary)
        self.assertNotIn("establishment_entries", source)

    def test_the_records_export_drops_the_columns_that_carried_blanket_claims(self):
        self._entry(5, permanence_plan="verified farm event data", methodology_template="USDA_X")
        archive = zipfile.ZipFile(io.BytesIO(export_establishment_records_zip(self.est)))
        lines = archive.read("carbon_entries.csv").decode().splitlines()
        header = next(line for line in lines if "co2e_amount" in line).split(",")
        for column in ("explanation_text", "methodology_template", "permanence_plan"):
            self.assertNotIn(column, header)
        self.assertNotIn("verified farm event data", "\n".join(lines))
        self.assertNotIn("USDA_X", "\n".join(lines))


class NoBlanketProvenanceAsPracticeOrRecommendationTests(_Farm):
    def test_a_factor_flag_is_not_listed_as_a_sustainability_practice(self):
        """It was: "EPA/USDA emission factors" appended to a scan's practices (2026-11-05)."""
        import inspect

        from history.serializers_consumer import EnhancedHistoryScanSerializer

        source = inspect.getsource(EnhancedHistoryScanSerializer.get_sustainability_practices)
        self.assertNotIn('append("EPA/USDA', source)

    def test_the_wizard_recommendations_claim_no_verification(self):
        import inspect
        import re

        from carbon.services import event_carbon_calculator

        source = inspect.getsource(event_carbon_calculator)
        # The recommendation `message`s are what the activity wizard renders (docstrings are not).
        messages = re.findall(r'"message":\s*"([^"]*)"', source)
        self.assertTrue(messages, "the guard must read real messages")
        offenders = [m for m in messages if re.search(r"verified|EPA/USDA", m, re.I) and "not a verified" not in m]
        self.assertEqual(offenders, [])

    def test_the_wizard_recommendations_name_no_agency_as_their_source(self):
        """The wizard printed each item's `source` ("EPA Greenhouse Gas Emission Factors Hub" on a
        pesticide, "USDA Nutrient Management Guidelines") as where the advice came from."""
        import inspect

        calculator = EventCarbonCalculator()
        for name in ("_generate_epa_chemical_recommendations", "_generate_epa_production_recommendations"):
            with self.subTest(name):
                source = inspect.getsource(getattr(calculator, name))
                self.assertIn('"message":', source)  # read the real generator
                self.assertNotIn('"source":', source)

    def test_the_wizard_impact_endpoint_claims_no_agency_verification(self):
        """calculate_event_carbon_impact answered "EPA Verified" / "USDA Verified" with a blanket
        "EPA/USDA" source (review of back #308)."""
        from pathlib import Path

        import carbon.views

        text = Path(carbon.views.__file__).read_text(encoding="utf-8")
        start = text.index("def calculate_event_carbon_impact(request):")
        body = text[start : text.index("\ndef ", start + 1)]
        self.assertIn('"verification_badge"', body)  # read the real function
        for claim in ('"EPA Verified"', '"USDA Verified"', '"EPA/USDA"', '"USDA"', '"Industry Standards"'):
            self.assertNotIn(claim, body)


class ChemicalSourcesAreTheFactorsAppliedTests(_Farm):
    """`data_sources` listed the N, P, K and fuel sources plus a fixed USDA ARS line for EVERY
    chemical, pesticides included (review of back #308). It now names the factors applied."""

    def _calc(self, **kw):
        from carbon.services.verified_emission_factors import VerifiedEmissionFactors as V

        args = dict(
            chemical_type="PE",
            volume_liters=10.0,
            area_hectares=1.0,
            npk_content={},
            concentration=50.0,
            application_fuel_type="diesel",
            application_fuel_consumed=5.0,
            application_fuel_unit="L",
        )
        args.update(kw)
        return V, V.calculate_chemical_application_emissions(**args)

    def test_a_pesticide_cites_the_pesticide_factor_and_its_fuel_only(self):
        V, result = self._calc()
        factors = V.EPA_CHEMICAL_FACTORS
        self.assertIn(factors["pesticide_manufacturing"].source, result["data_sources"])
        self.assertIn(factors["application_fuel"].source, result["data_sources"])
        for name in ("nitrogen_fertilizer", "phosphorus_fertilizer", "potassium_fertilizer"):
            if factors[name].source not in (
                factors["pesticide_manufacturing"].source,
                factors["application_fuel"].source,
            ):
                self.assertNotIn(factors[name].source, result["data_sources"], name)
        self.assertNotIn("USDA Agricultural Research Service - Chemical Application Methods", result["data_sources"])

    def test_an_estimated_factor_is_reported_as_one(self):
        _V, result = self._calc(chemical_type="FE", npk_content={"N": 10, "P": 10, "K": 10}, concentration=None)
        self.assertIn("internal_estimate", result["factor_provenance"])

    def test_a_published_badge_needs_every_applied_factor_published(self):
        from pathlib import Path

        import carbon.views

        text = Path(carbon.views.__file__).read_text(encoding="utf-8")
        start = text.index("def calculate_event_carbon_impact(request):")
        body = text[start : text.index("\ndef ", start + 1)]
        self.assertIn('if provenance == {"published"} else', body)
