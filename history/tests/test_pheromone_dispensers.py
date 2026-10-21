"""Pheromone dispensers for mating disruption can be recorded as what they are.

WHAT WAS WRONG (browser run on a WA organic apple orchard, 2026-10-20)
---------------------------------------------------------------------
Mating disruption is standard on organic apples: a few hundred pheromone dispensers per acre,
hung in the canopy by hand. The input-application form could not record one honestly:

  * the amount unit offered only liquid and weight measures, no count;
  * the application method offered only spray, soil and fumigation methods;
  * the form required a pesticide concentration, which a dispenser does not have in that sense.

So the grower guessed a weight, picked a spray method, and the record printed into the certifier
packet and the CA PUR as a spray of a made-up quantity.

WHAT THIS PINS
--------------
A dispenser application saves with a count unit and a hand-placement method and no
concentration; the count round-trips unchanged; carbon never reads the count as a mass or a
volume; the audit export prints the method in words and the amount as a count; the PUR carries
the count as recorded, notes that it is not pounds or gallons, and ticks "Other", never Ground.
None of this reads the sibling repository.
"""

import re
from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.utils.unit_converter import UnitConverter
from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor
from common.field_registry import APPLICATION_METHOD, SCHOOLSITE_CODE_SUGGESTION, UNIT_VOLUME, is_count_unit
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.serializers import UpdateChemicalEventSerializer
from history.services.audit_export_service import AuditExportService
from history.services.pur_export_service import PURExportService
from product.models import Parcel, Product
from users.models import User, WorksIn


def _flatten(elements) -> str:
    """Every string the flowables carry, cell by cell, the way the PDF prints them."""
    out = []
    for el in elements:
        text = getattr(el, "text", None)
        if isinstance(text, str):
            out.append(text)
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                t = getattr(cell, "text", None)
                out.append(t if isinstance(t, str) else str(cell))
    return re.sub(r"\s+", " ", " ".join(out))


class _Orchard(TestCase):
    """A 4-acre organic apple block, codling moth mating disruption at 300 dispensers/acre."""

    def setUp(self):
        self.user = User.objects.create_user(email="dispensers@test.com", password="x")
        self.company = Company.objects.create(name="Fictional Orchard Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(
            name="Fictional Block",
            company=self.company,
            address="1 Orchard Rd",
            city="Fresno",
            state="CA",
            zip_code="93701",
        )
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)
        self.history = History.objects.create(
            name="Honeycrisp 2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Apples"),
            operator=self.user,
            start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
            published=False,
        )

    def _dispensers(self, **extra):
        values = dict(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            date=datetime(2026, 4, 20, 9, tzinfo=dt_tz.utc),
            commercial_name="Isomate CM Flex",
            volume_numeric=Decimal("1200"),
            volume_unit="dispensers",
            area_numeric=Decimal("4"),
            area_unit="acres",
            way_of_application="hand_dispenser",
        )
        values.update(extra)
        return ChemicalEvent.objects.create(**values)


class ChoicesTests(TestCase):
    def test_the_count_unit_and_the_method_are_registered_choices(self):
        self.assertIn("dispensers", [code for code, _ in UNIT_VOLUME])
        self.assertIn("hand_dispenser", [code for code, _ in APPLICATION_METHOD])
        self.assertTrue(is_count_unit("dispensers"))
        for measure in ("gal", "L", "fl_oz", "oz_wt", "oz", "kg", "lbs", "", None):
            self.assertFalse(is_count_unit(measure), measure)

    def test_the_model_columns_accept_them(self):
        for field in ("volume_unit", "quantity_purchased_unit"):
            choices = [c for c, _ in ChemicalEvent._meta.get_field(field).choices]
            self.assertIn("dispensers", choices, field)
        methods = [c for c, _ in ChemicalEvent._meta.get_field("application_method_structured").choices]
        self.assertIn("hand_dispenser", methods)

    def test_the_schoolsite_suggestion_is_manual_placement(self):
        # 3 CCR 6691(b): 5121 "Manual placement (e.g. twist ties)".
        self.assertEqual(SCHOOLSITE_CODE_SUGGESTION["hand_dispenser"], "5121")


class SavesWithoutConcentrationTests(_Orchard):
    """The wizard's payload shape for a dispenser application, with no concentration at all."""

    def _create(self, payload):
        base = {
            "history": self.history.pk,
            "type": "PE",
            "date": timezone.now().isoformat(),
            "commercial_name": "Isomate CM Flex",
            "description": "Codling moth mating disruption",
        }
        base.update(payload)
        serializer = UpdateChemicalEventSerializer(data=base)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save()

    def test_a_dispenser_application_saves_and_round_trips(self):
        event = self._create(
            {
                "volume_applied": "1200",
                "volume_unit": "dispensers",
                "area_treated": "4",
                "area_unit": "acres",
                "application_method": "hand_dispenser",
                "quantity_purchased": "1500",
                "quantity_purchased_unit": "dispensers",
            }
        )
        event.refresh_from_db()
        self.assertIsNone(event.concentration)
        self.assertEqual(float(event.volume_numeric), 1200.0)
        self.assertEqual(event.volume_unit, "dispensers")
        self.assertEqual(event.quantity_purchased_unit, "dispensers")
        self.assertEqual(event.way_of_application, "hand_dispenser")

        data = UpdateChemicalEventSerializer(event).data
        self.assertEqual(data["volume_unit"], "dispensers")
        self.assertEqual(float(data["volume_applied"]), 1200.0)
        self.assertEqual(data["application_method"], "hand_dispenser")


class CarbonNeverReadsACountAsAMeasureTests(_Orchard):
    def test_the_converter_calls_a_count_neither_mass_nor_volume(self):
        self.assertTrue(UnitConverter.is_count_unit("dispensers"))
        self.assertFalse(UnitConverter.is_mass_unit("dispensers"))
        self.assertFalse(UnitConverter.is_volume_unit("dispensers"))

    def test_the_stored_record_computes_nothing_from_the_count_and_says_why(self):
        event = self._dispensers()
        data = EventCarbonCalculator()._extract_chemical_event_data(event)
        self.assertTrue(data["amount_is_count"])
        self.assertEqual(data["volume_liters"], 0.0)
        self.assertIsNone(data["chemical_mass_kg"])

        result = EventCarbonCalculator().calculate_chemical_event_impact(event)
        self.assertEqual(result["co2e"], 0.0)
        self.assertEqual(result["calculation_method"], "amount_is_count_not_converted")
        self.assertIn("count (1200 dispensers)", result["limitations"])

    def test_the_preview_does_not_read_the_count_as_litres(self):
        processed = OptimizedEventProcessor._process_chemical_event(
            {
                "type": "PE",
                "volume_numeric": "1200",
                "volume_unit": "dispensers",
                "area_numeric": "4",
                "area_unit": "acres",
                "application_method": "hand_dispenser",
            }
        )
        self.assertEqual(processed["volume"], 0.0)
        self.assertIsNone(processed["chemical_mass_kg"])
        self.assertEqual(processed["original_volume_unit"], "dispensers")

        # Review on back#192: the preview fell into the "invalid inputs" zero and still called
        # itself "epa_usda_verified". It now says nothing was calculated, and why.
        result = OptimizedCarbonCalculator().calculate_chemical_impact_optimized(processed)
        self.assertEqual(result["co2e"], 0.0)
        self.assertEqual(result["verification_status"], "insufficient_data")
        self.assertEqual(result["calculation_method"], "amount_is_count_not_converted")
        self.assertIn("count (1200 dispensers)", result["limitations"])

    def test_a_legacy_free_text_amount_is_still_a_count(self):
        # Review on back#192: with volume_numeric NULL and an unparseable `volume`, the routing
        # was skipped and the string parser assumed litres. The column decides.
        event = self._dispensers(volume_numeric=None, volume="approx 1200")
        data = EventCarbonCalculator()._extract_chemical_event_data(event)
        self.assertTrue(data["amount_is_count"])
        self.assertEqual(data["volume_liters"], 0.0)
        result = EventCarbonCalculator().calculate_chemical_event_impact(event)
        self.assertEqual(result["co2e"], 0.0)
        self.assertEqual(result["calculation_method"], "amount_is_count_not_converted")
        self.assertIn("approx 1200 dispensers", result["limitations"])


class AuditExportTests(_Orchard):
    def test_the_log_prints_the_method_in_words_and_the_amount_as_a_count(self):
        self._dispensers()
        text = _flatten(AuditExportService(self.history, certification_type="organic")._build_chemical_log())
        self.assertIn("Hand-placed dispensers", text)
        self.assertNotIn("hand_dispenser", text)
        self.assertIn("1200.00 dispensers (300.00 dispensers/acre)", text)
        # Never presented as a spray.
        self.assertNotIn("Ground spray", text)
        self.assertNotIn("Air-blast", text)


class PURExportTests(_Orchard):
    def test_the_row_carries_the_count_ticks_other_and_says_it_is_not_a_weight(self):
        self._dispensers(date=datetime(2026, 4, 20, 9, tzinfo=dt_tz.utc))
        row = PURExportService(self.est, 4, 2026).build_rows()[0]
        self.assertEqual(row["application_method"], "Other (hand-placed dispensers)")
        self.assertEqual(row["total_product_used"], "1200.00 dispensers")
        self.assertIn({"code": "product_amount_is_count", "amount": "1200.00 dispensers"}, row["flags"])
        self.assertIn("not a weight or volume", row["notes"])

    def test_a_measured_amount_raises_no_count_flag(self):
        self._dispensers(volume_numeric=Decimal("12"), volume_unit="gal", way_of_application="air_blast")
        row = PURExportService(self.est, 4, 2026).build_rows()[0]
        self.assertNotIn("product_amount_is_count", [f["code"] for f in row["flags"]])

    def test_near_a_school_the_suggested_code_is_manual_placement(self):
        self.parcel.ca_near_schoolsite = True
        self.parcel.save(update_fields=["ca_near_schoolsite"])
        self._dispensers()
        row = PURExportService(self.est, 4, 2026).build_rows()[0]
        flag = next(f for f in row["flags"] if f["code"] == "schoolsite_method_code_required")
        self.assertEqual(flag["suggested"], "5121")
