"""A carbon figure names the source its factors cite, never an agency that published none of them.

Overall review 2026-11, OV-FJ-C17 (2026-11-22).

WHAT WAS WRONG
--------------
* `_add_enhanced_usda_metadata` runs on every US figure and copied
  `get_enhanced_calculation_metadata()` over it: `data_source` "USDA Agricultural Research
  Service", `methodology` "USDA emission factors with regional adjustments" and
  `usda_compliance` True. Each calculation had already stated its own source (an EPA 40 CFR 98
  row, eGRID, a Trazo estimate), and the copy replaced it. The stored `CarbonEntry.data_source`
  kept the agency's name, and the record API served it as both `data_source` and
  `calculation_method`, which the event detail modal prints under "Calculation Method:". Back
  #426 (2026-11-13) put the chemical source back; every other event type kept the blanket.
* An equipment fuel figure named the same agency outright, for a diesel factor from EPA 40 CFR
  Part 98 Table C-1.
* Six per-hectare diesel defaults, labelled Trazo estimates by provenance, carried
  "USDA Agricultural Research Service - <topic>" as their `source`, the string printed wherever
  `data_sources` is.
* The audit PDF cover said "Emission factors sourced from EPA 40 CFR Part 98 and USDA
  Agricultural Research Service." No factor Trazo applies is published by USDA
  (.claude/rules/carbon-methodology.md).

Found by the review of back #516, once each figure kept its own source:
* general events cited "EPA Training Program Carbon Assessment (2024)" and two siblings, documents
  that do not exist, for Trazo estimates (`EnhancedEmissionFactors`);
* a production figure listed its per-hectare default even when measured fuel made the number, and
  the diesel row for any liquid fuel;
* the joined sources were cut at 200 characters mid-word;
* general, business and hour-rate equipment figures kept the published-factor status
  ("epa_usda_sourced") that `_add_enhanced_usda_metadata` stamps on every US figure.

WHAT THIS PINS
--------------
* no factor source and no regional metadata names an agency without a document;
* each non-chemical figure keeps the source its calculation stated, computed and stored;
* a row stored before the fix is served with its source as not stated (None);
* the audit cover states the sources per input class;
* a production figure names only the factors that made it;
* sources are joined whole and stored whole (carbon 0058);
* a figure resting on a Trazo default is an `estimate`, a zero is `no_factor_applied`.

It does not read the sibling repository.
"""

from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings

from carbon.choices import FUEL_TYPE_FACTORS
from carbon.event_link import entries_for_event
from carbon.models import CarbonEntry
from carbon.services.enhanced_emission_factors import EnhancedEmissionFactors
from carbon.services.enhanced_usda_factors import EnhancedUSDAFactors
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.services.verified_emission_factors import (
    AGENCY_WITHOUT_DOCUMENT,
    DATA_SOURCE_MAX_LENGTH,
    VERIFICATION_STATUS_ESTIMATE,
    EmissionFactor,
    VerifiedEmissionFactors,
    calculation_as_served,
    join_sources,
    stated_data_source,
)
from company.models import Company, Establishment
from history.models import BusinessEvent, EquipmentEvent, GeneralEvent, PestManagementEvent, Production, ProductionEvent
from history.serializers import EquipmentEventSerializer, GeneralEventSerializer
from history.services.records_export import FACTOR_SOURCES_BY_CLASS
from product.models import Parcel, Product
from users.models import User, WorksIn

BLANKET = "USDA Agricultural Research Service"


def _names_an_agency_without_a_document(text):
    return any(marker in str(text or "") for marker in AGENCY_WITHOUT_DOCUMENT)


def _all_factor_sources():
    """(where, source) for every EmissionFactor on the class and every fuel row in choices.py."""
    for dict_name in dir(VerifiedEmissionFactors):
        container = getattr(VerifiedEmissionFactors, dict_name) if dict_name.isupper() else None
        if isinstance(container, dict):
            for key, factor in container.items():
                if isinstance(factor, EmissionFactor):
                    yield f"{dict_name}.{key}", factor.source
    for fuel, row in FUEL_TYPE_FACTORS.items():
        yield f"FUEL_TYPE_FACTORS.{fuel}", row["source"]


class SourcesStatedTests(SimpleTestCase):
    def test_no_factor_source_names_an_agency_without_a_document(self):
        sources = list(_all_factor_sources())
        self.assertGreater(len(sources), 40, "factor sweep found almost nothing: did the class move?")
        offenders = [f"{where}: {source!r}" for where, source in sources if _names_an_agency_without_a_document(source)]
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_regional_metadata_states_no_source(self):
        metadata = EnhancedUSDAFactors().get_enhanced_calculation_metadata("apples", "WA")
        for key in ("data_source", "methodology", "usda_compliance", "factors_verified"):
            self.assertNotIn(key, metadata)

    def test_a_calculation_keeps_its_own_source_else_the_factors_it_listed(self):
        stated = EventCarbonCalculator._stated_source
        self.assertEqual(stated({"data_source": "EPA eGRID 2023", "data_sources": ["x"]}), "EPA eGRID 2023")
        self.assertEqual(stated({"data_sources": ["A", "B", "A"]}), "A; B")
        self.assertEqual(stated({}), "No factor applied")

    def test_stored_text_naming_the_agency_reads_as_not_stated(self):
        self.assertIsNone(stated_data_source(BLANKET))
        self.assertIsNone(stated_data_source("USDA ARS (fertilizer manufacturing)"))
        self.assertIsNone(stated_data_source("USDA emission factors with regional adjustments"))
        self.assertIsNone(stated_data_source(""))
        epa = FUEL_TYPE_FACTORS["diesel"]["source"]
        self.assertEqual(stated_data_source(epa), epa)

    def test_a_stored_calculation_dict_is_served_without_the_agency(self):
        served = calculation_as_served(
            {
                "co2e": 4.2,
                "data_source": BLANKET,
                "methodology": "USDA emission factors with regional adjustments",
                "usda_compliance": True,
                "data_sources": [f"{BLANKET} - Field Operations", "EPA eGRID 2023"],
            }
        )
        self.assertEqual(served["co2e"], 4.2)
        self.assertIsNone(served["data_source"])
        self.assertIsNone(served["methodology"])
        self.assertNotIn("usda_compliance", served)
        self.assertEqual(served["data_sources"], ["EPA eGRID 2023"])

    def test_general_event_defaults_say_they_are_trazo_estimates(self):
        for key, factor in EnhancedEmissionFactors.GENERAL_FACTORS.items():
            self.assertTrue(factor.source.startswith("Trazo estimate"), f"{key}: {factor.source!r}")

    def test_sources_are_joined_whole_never_cut_mid_entry(self):
        a, b, c = "A" * 150, "B" * 150, "C" * 150
        self.assertEqual(join_sources([a, b]), f"{a}; {b}")
        self.assertEqual(join_sources([a, b, c], limit=320), f"{a}; {b}; and 1 more")
        self.assertEqual(join_sources([a, b, c], limit=200), f"{a}; and 2 more")
        self.assertEqual(join_sources(["x" * 30], limit=10), "x" * 9 + "…")
        self.assertEqual(join_sources([]), "No factor applied")

    def test_an_irrigation_figure_stores_both_of_its_sources(self):
        result = VerifiedEmissionFactors.calculate_drought_irrigation_emissions(
            water_volume_gallons=325851, pump_depth_ft=120
        )
        self.assertEqual(len(result["data_sources"]), 2, result["data_sources"])
        joined = join_sources(result["data_sources"])
        self.assertGreater(len(joined), 200, "the case the old 200-character cut broke")
        self.assertEqual(joined, "; ".join(result["data_sources"]))
        self.assertEqual(CarbonEntry._meta.get_field("data_source").max_length, DATA_SOURCE_MAX_LENGTH)


# The US branch of `_add_enhanced_usda_metadata` is the one that wrote the blanket.
@override_settings(TRAZO_OPERATING_COUNTRY="US")
class _Season(TestCase):
    """A fictional Washington apple block with one open season."""

    def setUp(self):
        self.user = User.objects.create_user(email="agency-source@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Fictional Bench Orchard")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Fictional Bench", company=self.company, state="WA")
        self.history = Production.objects.create(
            name="Gala 2026",
            parcel=Parcel.objects.create(name="North Block", establishment=est, area=4.0),
            product=Product.objects.create(name="Apples"),
            operator=self.user,
            start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
        )
        self.calc = EventCarbonCalculator()
        self.date = datetime(2026, 6, 3, 8, 0, tzinfo=dt_tz.utc)

    def _equipment(self, **fields):
        return EquipmentEvent.objects.create(history=self.history, date=self.date, description="pass", **fields)

    def assertStatesNoAgency(self, result, event):
        self.assertTrue(result.get("data_source"), "a figure always states a source, even 'No factor applied'")
        for key in ("data_source", "methodology", "calculation_method"):
            self.assertFalse(_names_an_agency_without_a_document(result.get(key)), f"{key}: {result.get(key)!r}")
        for source in result.get("data_sources") or []:
            self.assertFalse(_names_an_agency_without_a_document(source), source)
        self.assertNotIn("usda_compliance", result)
        for entry in entries_for_event(event, link=False):
            self.assertFalse(_names_an_agency_without_a_document(entry.data_source), entry.data_source)


class WrittenSourceTests(_Season):
    def test_equipment_fuel_cites_the_epa_row_it_applied(self):
        event = self._equipment(type="FC", fuel_consumed=Decimal("40"), fuel_unit="L", fuel_type="diesel")
        result = self.calc.calculate_equipment_event_impact(event)
        self.assertGreater(result["co2e"], 0)
        self.assertEqual(result["data_source"], FUEL_TYPE_FACTORS["diesel"]["source"])
        self.assertStatesNoAgency(result, event)
        stored = list(entries_for_event(event, link=False))
        self.assertEqual(len(stored), 1, "expected the fuel figure to be stored")
        self.assertEqual(stored[0].data_source, FUEL_TYPE_FACTORS["diesel"]["source"])

    def test_equipment_electricity_cites_the_grid_factor_it_applied(self):
        event = self._equipment(type="FC", fuel_consumed=Decimal("120"), fuel_type="electric")
        result = self.calc.calculate_equipment_event_impact(event)
        self.assertEqual(result["data_source"], VerifiedEmissionFactors.get_country_electricity_factor().source)
        self.assertStatesNoAgency(result, event)

    def test_a_breakdown_with_fuel_cites_the_diesel_factor_it_applied(self):
        event = self._equipment(type="BD", fuel_consumed=Decimal("10"), fuel_unit="L")
        result = self.calc.calculate_equipment_event_impact(event)
        self.assertGreater(result["co2e"], 0)
        self.assertEqual(
            result["data_source"], VerifiedEmissionFactors.EPA_DIESEL_FACTORS["agricultural_equipment"].source
        )
        self.assertStatesNoAgency(result, event)

    def test_a_harvest_estimated_from_its_area_names_the_trazo_estimate(self):
        event = ProductionEvent.objects.create(
            history=self.history, type="HA", date=self.date, description="First pick", area_covered=Decimal("4")
        )
        result = self.calc.calculate_production_event_impact(event)
        self.assertEqual(
            result["data_sources"],
            [
                VerifiedEmissionFactors.EPA_DIESEL_FACTORS["agricultural_equipment"].source,
                "Trazo estimate of diesel per hectare, harvesting",
            ],
        )
        self.assertStatesNoAgency(result, event)

    def test_a_harvest_with_recorded_fuel_names_the_epa_factor(self):
        event = ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=self.date,
            description="Second pick",
            area_covered=Decimal("4"),
            fuel_type="diesel",
            fuel_consumed=Decimal("12.5"),
        )
        result = self.calc.calculate_production_event_impact(event)
        diesel = VerifiedEmissionFactors.EPA_FUEL_FACTORS["diesel"].source
        self.assertEqual(result["data_sources"], [diesel], "measured fuel: the per-hectare default made nothing")
        self.assertEqual(result["data_source"], diesel)
        self.assertStatesNoAgency(result, event)

    def test_a_measured_gasoline_harvest_cites_the_gasoline_row(self):
        event = ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=self.date,
            description="Third pick",
            area_covered=Decimal("4"),
            fuel_type="gasoline",
            fuel_consumed=Decimal("6"),
        )
        result = self.calc.calculate_production_event_impact(event)
        self.assertEqual(result["data_sources"], [VerifiedEmissionFactors.EPA_FUEL_FACTORS["gasoline"].source])

    def test_scouting_and_a_general_activity_state_no_agency(self):
        pest = PestManagementEvent.objects.create(
            history=self.history, type="SC", description="scouting", date=self.date
        )
        self.assertStatesNoAgency(self.calc.calculate_pest_management_event_impact(pest), pest)
        general = GeneralEvent.objects.create(history=self.history, name="Walked rows", description="d", date=self.date)
        self.assertStatesNoAgency(self.calc.calculate_general_event_impact(general), general)


class StatusFollowsTheBasisTests(_Season):
    """A figure no published factor made never carries the published label."""

    def _stored(self, event):
        entries = list(entries_for_event(event, link=False))
        self.assertEqual(len(entries), 1, "expected one stored carbon entry")
        return entries[0]

    def test_a_general_event_is_a_trazo_estimate(self):
        event = GeneralEvent.objects.create(
            history=self.history, name="Training day", description="training session for the crew", date=self.date
        )
        result = self.calc.calculate_general_event_impact(event)
        self.assertGreater(result["co2e"], 0)
        self.assertEqual(result["verification_status"], VERIFICATION_STATUS_ESTIMATE)
        self.assertFalse(result["usda_factors_based"])
        self.assertIn("trazo_estimate_factor", result["breakdown"]["estimate_reasons"])
        self.assertTrue(result["data_source"].startswith("Trazo estimate"), result["data_source"])
        self.assertNotIn("verified", result["transparency_note"])
        # A general event stores no carbon (history/signals.py); this figure reaches the form preview.
        self.assertEqual(list(entries_for_event(event, link=False)), [])

    def test_maintenance_hours_are_an_estimate(self):
        # `hours_operated` is read on the structured branch, which a recorded fuel figure (here 0) selects.
        event = self._equipment(
            type="MN", fuel_consumed=Decimal("0"), hours_operated=Decimal("3"), equipment_name="Large tractor"
        )
        result = self.calc.calculate_equipment_event_impact(event)
        self.assertGreater(result["co2e"], 0)
        self.assertEqual(result["verification_status"], VERIFICATION_STATUS_ESTIMATE)
        self.assertFalse(result["usda_factors_based"])
        entry = self._stored(event)
        self.assertEqual(entry.verification_status, VERIFICATION_STATUS_ESTIMATE)
        self.assertFalse(entry.usda_factors_based)
        served = EquipmentEventSerializer(event).data["carbon_data"]
        self.assertEqual(served["verification_status"], "estimate")
        self.assertFalse(served["usda_factors_based"])

    def test_a_zero_names_no_factor(self):
        calibration = self._equipment(type="CA")
        self.assertEqual(
            self.calc.calculate_equipment_event_impact(calibration)["verification_status"], "no_factor_applied"
        )
        inspection = BusinessEvent.objects.create(
            history=self.history, type=BusinessEvent.INSPECTION, description="annual inspection", date=self.date
        )
        result = self.calc.calculate_business_event_impact(inspection)
        self.assertEqual(result["verification_status"], "no_factor_applied")
        self.assertFalse(result["usda_factors_based"])

    def test_recorded_fuel_keeps_the_published_label(self):
        event = self._equipment(type="FC", fuel_consumed=Decimal("40"), fuel_unit="L", fuel_type="diesel")
        result = self.calc.calculate_equipment_event_impact(event)
        self.assertEqual(result["verification_status"], "factors_verified")
        self.assertTrue(result["usda_factors_based"])


class ServedSourceTests(_Season):
    def test_a_row_stored_with_the_agency_is_served_as_not_stated(self):
        event = self._equipment(type="FC", fuel_consumed=Decimal("40"), fuel_unit="L", fuel_type="diesel")
        entry = list(entries_for_event(event, link=False))[0]
        # Today's row is served as written.
        served = EquipmentEventSerializer(event).data["carbon_data"]
        self.assertEqual(served["data_source"], FUEL_TYPE_FACTORS["diesel"]["source"])
        self.assertEqual(served["calculation_method"], FUEL_TYPE_FACTORS["diesel"]["source"])
        # A row written before 2026-11-22 carried the blanket.
        CarbonEntry.objects.filter(pk=entry.pk).update(data_source=BLANKET)
        served = EquipmentEventSerializer(event).data["carbon_data"]
        self.assertIsNone(served["data_source"])
        self.assertIsNone(served["calculation_method"])
        self.assertGreater(served["co2e"], 0, "the figure itself is still served")

    def test_an_old_calculation_on_the_record_is_served_without_the_agency(self):
        event = GeneralEvent.objects.create(history=self.history, name="Walked rows", description="d", date=self.date)
        CarbonEntry.objects.filter(pk__in=[e.pk for e in entries_for_event(event, link=False)]).delete()
        GeneralEvent.objects.filter(pk=event.pk).update(
            extra_data={
                "carbon_calculation": {
                    "co2e": 1.5,
                    "data_source": BLANKET,
                    "methodology": "USDA emission factors with regional adjustments",
                    "usda_compliance": True,
                }
            }
        )
        event.refresh_from_db()
        served = GeneralEventSerializer(event).data["carbon_data"]
        self.assertEqual(served["co2e"], 1.5, "sanity: the old calculation path was read")
        self.assertIsNone(served["data_source"])
        self.assertIsNone(served["methodology"])
        self.assertNotIn("usda_compliance", served)


@override_settings(TRAZO_OPERATING_COUNTRY="US")
class AuditCoverTests(_Season):
    def test_the_cover_states_sources_per_input_class(self):
        from history.services.audit_export_service import AuditExportService
        from history.tests.test_packet_carbon_scope import _flatten

        svc = AuditExportService(self.history, certification_type="all")
        self.assertTrue(svc.carbon_in_scope, "sanity: the sentence prints only where carbon is in scope")
        text = "\n".join(_flatten(f) for f in svc._build_cover_page())
        self.assertIn(f"Emission factors sourced per input class: {FACTOR_SOURCES_BY_CLASS}.", text)
        self.assertNotIn("Agricultural Research Service", text)
