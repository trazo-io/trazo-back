"""A spray record holds the state application facts Washington asks for (OV-FJ-C11).

WHAT WAS MISSING (overall review 2026-11, OV-RK-C03 / OV-FJ-C11)
---------------------------------------------------------------
WAC 16-228-1320(1) (WSR 25-22-065, effective 2026-01-01) covers every person applying pesticides
to more than one acre of agricultural land, organic orchards included. A Trazo spray had a
five-option weather select and nowhere to put: (e) the wind direction and speed in mph and the
temperature in degrees Fahrenheit, (h) the carrier volume ("gallons per acre of output volume"),
(k) the apparatus license plate, (l) the applicator's address and phone, (n) a commercial firm's
address.

WHAT THIS PINS
--------------
Nine optional, operator-typed columns on ChemicalEvent and every reader of them: their ranges and
choices, the serializer round trip, "Not applicable (method)" for drip and subsurface, the packet
table and the audit CSV, the buyer page (certifier-only), one tank over several parcels (shared,
with a tank total refused) and a correction. None of this reads the sibling repository; the
frontend mirror of the buyer-page list is held by test_certifier_only_list_parity.
"""

import csv
import io
import json
import re
import uuid
from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.amendments import AmendmentError, amendable_fields, apply_amendment
from history.constants import CHEMICAL_EVENT_TYPE
from history.models import ChemicalEvent, EventAmendment, History
from history.serializers import ChemicalEventSerializer, PublicHistorySerializer, UpdateChemicalEventSerializer
from history.services import multi_target
from history.services.application_conditions import (
    CARRIER_UNIT_MISSING,
    air_temperature_text,
    application_conditions,
    carrier_text,
    wind_text,
)
from history.services.audit_export_service import AuditExportService, _method_label
from product.models import Parcel, Product
from users.models import User, WorksIn

NEW_FIELDS = (
    "wind_from",
    "wind_speed_mph",
    "air_temperature_f",
    "carrier_volume",
    "carrier_volume_unit",
    "apparatus_license_plate",
    "applicator_address",
    "applicator_phone",
    "commercial_firm_address",
)

FULL = {
    "wind_from": "NW",
    "wind_speed_mph": Decimal("4"),
    "air_temperature_f": Decimal("62"),
    "carrier_volume": Decimal("100"),
    "carrier_volume_unit": "gal_per_acre",
    "apparatus_license_plate": "C12345X",
    "applicator_address": "12 Orchard Lane, Wenatchee, WA 98801",
    "applicator_phone": "509-555-0142",
    "commercial_firm_address": "400 Valley Road, Yakima, WA 98901",
}


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
    """A fictional Washington orchard spraying an organic insecticide by air-blast."""

    def setUp(self):
        self.user = User.objects.create_user(email="wa-spray@test.com", password="x")
        self.company = Company.objects.create(name="Fictional Columbia Orchard")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(
            name="Fictional Bench", company=self.company, address="1 Orchard Rd", city="Wenatchee", state="WA"
        )
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)
        self.history = History.objects.create(
            name="Honeycrisp 2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Apples"),
            operator=self.user,
            start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
            published=True,
        )

    def _spray(self, **extra):
        values = dict(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            date=datetime(2026, 5, 2, 6, 30, tzinfo=dt_tz.utc),
            commercial_name="Entrust SC",
            volume_numeric=Decimal("24"),
            volume_unit="fl_oz",
            area_numeric=Decimal("4"),
            area_unit="acres",
            way_of_application="air_blast",
        )
        values.update(extra)
        return ChemicalEvent.objects.create(**values)

    def _serializer(self, payload, instance=None, partial=False):
        base = (
            {}
            if instance is not None
            else {
                "history": self.history.pk,
                "type": "PE",
                "date": "2026-05-02T06:30",
                "commercial_name": "Entrust SC",
            }
        )
        base.update(payload)
        return UpdateChemicalEventSerializer(instance=instance, data=base, partial=partial)


class RangesAndChoicesTests(_Orchard):
    def _refused(self, **values):
        event = ChemicalEvent(history=self.history, type="PE", commercial_name="Entrust SC", **values)
        with self.assertRaises(DjangoValidationError) as ctx:
            event.full_clean(exclude=["description", "date", "history"])
        return ctx.exception.message_dict

    def test_wind_speed_runs_0_to_150_mph(self):
        self.assertIn("wind_speed_mph", self._refused(wind_speed_mph=Decimal("150.1")))
        self.assertIn("wind_speed_mph", self._refused(wind_speed_mph=Decimal("-1")))

    def test_air_temperature_runs_minus_40_to_140_f(self):
        self.assertIn("air_temperature_f", self._refused(air_temperature_f=Decimal("140.5")))
        self.assertIn("air_temperature_f", self._refused(air_temperature_f=Decimal("-40.5")))

    def test_wind_from_is_one_of_eight_points_or_calm(self):
        self.assertEqual(
            [code for code, _ in ChemicalEvent.WIND_FROM_CHOICES],
            ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "calm"],
        )
        self.assertIn("wind_from", self._refused(wind_from="NNW"))

    def test_carrier_volume_is_above_zero_and_carries_a_real_unit(self):
        self.assertIn("carrier_volume", self._refused(carrier_volume=Decimal("0"), carrier_volume_unit="gal_per_acre"))
        self.assertIn("carrier_volume_unit", self._refused(carrier_volume=Decimal("100"), carrier_volume_unit="gpa"))
        self.assertEqual(
            [code for code, _ in ChemicalEvent.CARRIER_VOLUME_UNIT_CHOICES], ["gal_per_acre", "gal_total", "l_per_ha"]
        )

    def test_a_carrier_volume_without_its_unit_is_refused_by_the_model(self):
        self.assertEqual(self._refused(carrier_volume=Decimal("100"))["carrier_volume_unit"], [CARRIER_UNIT_MISSING])
        self.assertIn("carrier_volume", self._refused(carrier_volume_unit="gal_per_acre"))

    def test_a_full_reading_is_accepted(self):
        event = ChemicalEvent(history=self.history, type="PE", commercial_name="Entrust SC", **FULL)
        event.full_clean(exclude=["description", "date", "history"])


class SerializerRoundTripTests(_Orchard):
    def _wire(self):
        return {
            "wind_from": "NW",
            "wind_speed_mph": "4",
            "air_temperature_f": "62",
            "carrier_volume": "100",
            "carrier_volume_unit": "gal_per_acre",
            "apparatus_license_plate": "C12345X",
            "applicator_address": FULL["applicator_address"],
            "applicator_phone": FULL["applicator_phone"],
            "commercial_firm_address": FULL["commercial_firm_address"],
        }

    def test_every_new_field_saves_and_reads_back(self):
        serializer = self._serializer(self._wire())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        event = serializer.save()
        event.refresh_from_db()
        for name, value in FULL.items():
            self.assertEqual(getattr(event, name), value, name)

        read = ChemicalEventSerializer(event).data
        self.assertEqual(read["wind_from"], "NW")
        self.assertEqual(Decimal(read["wind_speed_mph"]), Decimal("4"))
        self.assertEqual(Decimal(read["air_temperature_f"]), Decimal("62"))
        self.assertEqual(Decimal(read["carrier_volume"]), Decimal("100"))
        self.assertEqual(read["carrier_volume_unit"], "gal_per_acre")
        self.assertEqual(read["apparatus_license_plate"], "C12345X")
        self.assertEqual(read["applicator_address"], FULL["applicator_address"])
        self.assertEqual(read["applicator_phone"], FULL["applicator_phone"])
        self.assertEqual(read["commercial_firm_address"], FULL["commercial_firm_address"])
        # The edit form reads the same serializer it writes through.
        update_read = UpdateChemicalEventSerializer(event).data
        for name in NEW_FIELDS:
            self.assertIn(name, update_read, name)

    def test_blank_numbers_from_the_form_clear_rather_than_400(self):
        event = self._spray(**FULL)
        serializer = self._serializer(
            {"wind_speed_mph": "", "air_temperature_f": "", "carrier_volume": "", "carrier_volume_unit": ""},
            instance=event,
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        event.refresh_from_db()
        self.assertIsNone(event.wind_speed_mph)
        self.assertIsNone(event.air_temperature_f)
        self.assertIsNone(event.carrier_volume)
        self.assertEqual(event.carrier_volume_unit, "")

    def test_out_of_range_readings_are_refused_by_the_api(self):
        serializer = self._serializer({"wind_speed_mph": "151", "air_temperature_f": "-41"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("wind_speed_mph", serializer.errors)
        self.assertIn("air_temperature_f", serializer.errors)

    def test_a_carrier_volume_and_its_unit_travel_together(self):
        serializer = self._serializer({"carrier_volume": "100"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("carrier_volume_unit", serializer.errors)
        # A partial edit that clears only the unit cannot leave the stored number unitless.
        event = self._spray(carrier_volume=Decimal("100"), carrier_volume_unit="gal_per_acre")
        serializer = self._serializer({"carrier_volume_unit": ""}, instance=event, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("carrier_volume_unit", serializer.errors)
        # And clearing only the number cannot leave the stored unit measuring nothing.
        serializer = self._serializer({"carrier_volume": ""}, instance=event, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("carrier_volume", serializer.errors)

    def test_the_applicator_contact_is_a_copy_on_the_record_not_a_link(self):
        """The owner's rule (2026-11-11): a later profile edit never rewrites a past record. The
        record holds its own text; nothing on it points at a row that could change later."""
        for name in ("applicator_name", "applicator_certification", "applicator_address", "applicator_phone"):
            field = ChemicalEvent._meta.get_field(name)
            self.assertFalse(field.is_relation, name)
            self.assertEqual(field.get_internal_type(), "CharField", name)


class NotApplicableByMethodTests(_Orchard):
    def test_drip_and_subsurface_print_not_applicable_instead_of_a_blank(self):
        drip = self._spray(way_of_application="drip")
        subsurface = self._spray(type="FE", way_of_application="subsurface")
        self.assertEqual(wind_text(drip, _method_label), "Not applicable (Drip / fertigation)")
        self.assertEqual(air_temperature_text(drip, _method_label), "Not applicable (Drip / fertigation)")
        self.assertEqual(wind_text(subsurface, _method_label), "Not applicable (Subsurface)")
        self.assertEqual(air_temperature_text(subsurface, _method_label), "Not applicable (Subsurface)")

    def test_a_spray_method_leaves_a_blank_a_blank(self):
        event = self._spray()
        self.assertIsNone(wind_text(event, _method_label))
        self.assertIsNone(air_temperature_text(event, _method_label))

    def test_a_reading_typed_on_an_exempt_method_is_still_printed(self):
        event = self._spray(way_of_application="drip", wind_from="calm", air_temperature_f=Decimal("58.5"))
        self.assertEqual(wind_text(event, _method_label), "calm")
        self.assertEqual(air_temperature_text(event, _method_label), "58.5 °F")


class WordingTests(SimpleTestCase):
    def _event(self, **values):
        return ChemicalEvent(way_of_application="air_blast", **values)

    def test_each_half_of_a_wind_reading_says_what_is_missing(self):
        self.assertEqual(wind_text(self._event(wind_from="NW", wind_speed_mph=Decimal("4.0"))), "from NW at 4 mph")
        self.assertEqual(wind_text(self._event(wind_from="NW")), "from NW, speed not recorded")
        self.assertEqual(wind_text(self._event(wind_speed_mph=Decimal("6.5"))), "6.5 mph, direction not recorded")
        self.assertEqual(wind_text(self._event(wind_from="calm", wind_speed_mph=Decimal("0"))), "calm, 0 mph")

    def test_temperature_and_carrier(self):
        self.assertEqual(air_temperature_text(self._event(air_temperature_f=Decimal("62.0"))), "62 °F")
        self.assertEqual(air_temperature_text(self._event(air_temperature_f=Decimal("-3.5"))), "-3.5 °F")
        self.assertEqual(
            carrier_text(self._event(carrier_volume=Decimal("100.00"), carrier_volume_unit="gal_per_acre")),
            "100 gal/acre",
        )
        self.assertEqual(
            carrier_text(self._event(carrier_volume=Decimal("935"), carrier_volume_unit="l_per_ha")), "935 L/ha"
        )
        self.assertEqual(
            carrier_text(self._event(carrier_volume=Decimal("400"), carrier_volume_unit="gal_total")), "400 gal total"
        )

    def test_nothing_recorded_prints_nothing(self):
        self.assertEqual(application_conditions(self._event()), [])


class PrintingTests(_Orchard):
    def test_the_packet_prints_every_fact_in_its_conditions_table(self):
        self._spray(**FULL)
        text = _flatten(AuditExportService(self.history, certification_type="organic")._build_chemical_log())
        self.assertIn("Application Conditions, Apparatus", text)
        for expected in (
            "from NW at 4 mph",
            "62 °F",
            "100 gal/acre",
            "C12345X",
            "12 Orchard Lane, Wenatchee, WA 98801",
            "509-555-0142",
            "400 Valley Road, Yakima, WA 98901",
        ):
            self.assertIn(expected, text, expected)

    def test_a_record_without_the_facts_adds_no_table(self):
        self._spray()
        text = _flatten(AuditExportService(self.history, certification_type="organic")._build_chemical_log())
        self.assertNotIn("Application Conditions, Apparatus", text)

    def test_the_packet_says_not_applicable_for_a_drip_application(self):
        self._spray(way_of_application="drip")
        text = _flatten(AuditExportService(self.history, certification_type="organic")._build_chemical_log())
        self.assertIn("Application Conditions, Apparatus", text)
        self.assertEqual(text.count("Not applicable (Drip / fertigation)"), 2)

    def test_the_audit_csv_carries_them_in_notes(self):
        self._spray(**FULL)
        raw = AuditExportService(self.history, certification_type="organic").generate_csv().getvalue()
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        header = next(r for r in rows if "Notes" in r and "Product / Input" in r)
        col, product_col = header.index("Notes"), header.index("Product / Input")
        notes = [r[col] for r in rows[rows.index(header) + 1 :] if len(r) > col and r[product_col] == "Entrust SC"]
        self.assertEqual(len(notes), 1)
        for expected in (
            "Wind: from NW at 4 mph",
            "Air temperature: 62 °F",
            "Carrier: 100 gal/acre",
            "Apparatus plate: C12345X",
            "Applicator address: 12 Orchard Lane, Wenatchee, WA 98801",
            "Applicator phone: 509-555-0142",
            "Firm address: 400 Valley Road, Yakima, WA 98901",
        ):
            self.assertIn(expected, notes[0], expected)
        # The header did not move: anyone's saved import mapping still lines up.
        self.assertNotIn("Wind", header)


class BuyerPageTests(_Orchard):
    def test_every_new_field_is_certifier_only(self):
        for name in NEW_FIELDS:
            self.assertIn(name, PublicHistorySerializer._CERTIFIER_ONLY_EVENT_FIELDS, name)

    def test_no_value_reaches_the_anonymous_payload(self):
        self._spray(
            **FULL,
            extra_data={"wind_from": "NW", "applicator_phone": "509-555-0142", "carrier_volume": "100"},
        )
        payload = PublicHistorySerializer(self.history).data
        chem = [e for e in payload.get("events") or [] if e.get("type") == "chemical"]
        self.assertEqual(len(chem), 1, "the spray must be on the payload for this check to mean anything")
        for name in NEW_FIELDS:
            self.assertNotIn(name, chem[0], name)
            self.assertNotIn(name, chem[0].get("extra_data") or {}, name)
        blob = json.dumps(payload, default=str)
        for value in ("C12345X", "509-555-0142", "Orchard Lane", "Valley Road"):
            self.assertNotIn(value, blob, value)


class MultiParcelTests(TestCase):
    def _envelope(self, **shared):
        return multi_target.check_envelope(
            {
                "event_type": CHEMICAL_EVENT_TYPE,
                "type": "PE",
                "date": "2026-05-02",
                **shared,
                "targets": [{"parcel": 1, "area_treated": "4"}, {"parcel": 2, "area_treated": "6"}],
            },
            CHEMICAL_EVENT_TYPE,
        )

    def test_the_new_fields_are_shared_facts_of_the_one_application(self):
        spec = multi_target.spec_for(CHEMICAL_EVENT_TYPE)
        for key in NEW_FIELDS:
            self.assertNotIn(key, spec.per_target_any(), key)
            self.assertNotIn(key, spec.refused, key)
            self.assertNotIn(key, spec.either, key)
        shared, _ = self._envelope(
            wind_from="NW", wind_speed_mph="4", carrier_volume="100", carrier_volume_unit="gal_per_acre"
        )
        self.assertEqual(shared["carrier_volume_unit"], "gal_per_acre")

    def test_a_tank_total_carrier_volume_is_refused(self):
        """One tank over two blocks: a total would be copied onto both records as if each got it all."""
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError) as ctx:
            self._envelope(carrier_volume="400", carrier_volume_unit="gal_total")
        self.assertIn("carrier_volume_unit=gal_total", str(ctx.exception.detail["refused"]))
        # A per-area unit is the same on every parcel, so it stays shared.
        self._envelope(carrier_volume="935", carrier_volume_unit="l_per_ha")

    def test_every_refused_value_is_a_real_choice_of_a_field_the_serializer_takes(self):
        fields = UpdateChemicalEventSerializer().fields
        for key, values in multi_target.spec_for(CHEMICAL_EVENT_TYPE).refused_values.items():
            self.assertIn(key, fields, key)
            self.assertTrue(set(values) <= set(fields[key].choices), (key, values))


class MultiParcelApiTests(_Orchard):
    def test_one_tank_on_two_blocks_writes_the_reading_on_every_record(self):
        self.parcel.current_history = self.history
        self.parcel.save(update_fields=["current_history"])
        south = Parcel.objects.create(name="South Block", establishment=self.est, area=6.0)
        south_season = History.objects.create(
            name="Gala 2026", parcel=south, operator=self.user, start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc)
        )
        south.current_history = south_season
        south.save(update_fields=["current_history"])

        group = str(uuid.uuid4())
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post(
            reverse("events-list"),
            {
                "event_type": CHEMICAL_EVENT_TYPE,
                "application_group": group,
                "date": "2026-05-02T06:30",
                "type": "PE",
                "commercial_name": "Entrust SC",
                "application_method": "air_blast",
                "volume_unit": "fl_oz",
                "area_unit": "acres",
                "wind_from": "NW",
                "wind_speed_mph": "4",
                "air_temperature_f": "62",
                "carrier_volume": "100",
                "carrier_volume_unit": "gal_per_acre",
                "apparatus_license_plate": "C12345X",
                "applicator_address": FULL["applicator_address"],
                "applicator_phone": FULL["applicator_phone"],
                "targets": [
                    {"parcel": self.parcel.id, "area_treated": "4", "volume_applied": "24"},
                    {"parcel": south.id, "area_treated": "6", "volume_applied": "36"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        records = ChemicalEvent.objects.filter(application_group=group)
        self.assertEqual(records.count(), 2)
        for record in records:
            self.assertEqual(record.wind_from, "NW")
            self.assertEqual(record.wind_speed_mph, Decimal("4"))
            self.assertEqual(record.air_temperature_f, Decimal("62"))
            self.assertEqual(record.carrier_volume, Decimal("100"))
            self.assertEqual(record.carrier_volume_unit, "gal_per_acre")
            self.assertEqual(record.apparatus_license_plate, "C12345X")
            self.assertEqual(record.applicator_phone, FULL["applicator_phone"])


class CorrectionTests(_Orchard):
    def _correct(self, event, field_name, new_value, reason="The spray log says otherwise."):
        return apply_amendment(
            event=event,
            event_type=CHEMICAL_EVENT_TYPE,
            field_name=field_name,
            new_value=new_value,
            reason=reason,
            user=self.user,
        )

    def test_every_new_field_is_correctable(self):
        names = {f.name for f in amendable_fields(ChemicalEvent)}
        for name in NEW_FIELDS:
            self.assertIn(name, names, name)

    def test_correcting_the_wind_speed_leaves_a_trail(self):
        event = self._spray(wind_from="NW", wind_speed_mph=Decimal("4"))
        self._correct(event, "wind_speed_mph", "6")
        event.refresh_from_db()
        self.assertEqual(event.wind_speed_mph, Decimal("6"))
        row = EventAmendment.objects.get(event_type=CHEMICAL_EVENT_TYPE, event_id=event.id)
        self.assertEqual(row.field_name, "wind_speed_mph")
        self.assertEqual(Decimal(row.original_value), Decimal("4"))
        self.assertEqual(Decimal(row.corrected_value), Decimal("6"))
        self.assertEqual(row.reason, "The spray log says otherwise.")

    def test_a_correction_cannot_write_an_impossible_reading(self):
        event = self._spray(wind_from="NW")
        with self.assertRaises(AmendmentError):
            self._correct(event, "wind_speed_mph", "151")
        with self.assertRaises(AmendmentError):
            self._correct(event, "wind_from", "NNW")
        event.refresh_from_db()
        self.assertIsNone(event.wind_speed_mph)
        self.assertEqual(event.wind_from, "NW")
        self.assertFalse(EventAmendment.objects.filter(event_type=CHEMICAL_EVENT_TYPE, event_id=event.id).exists())

    def test_the_applicator_phone_can_be_recorded_after_the_fact(self):
        event = self._spray(applicator_name="Javier Morales")
        self._correct(event, "applicator_phone", "509-555-0199", reason="Added from the licence card.")
        event.refresh_from_db()
        self.assertEqual(event.applicator_phone, "509-555-0199")
