"""A spray can say "not on my record" for its concentration and its clock time (OV-FJ-C12).

WHAT WAS WRONG (pilot rehearsal 2026-10-01, findings 3 and 8; overall review 2026-11)
------------------------------------------------------------------------------------
A grower typing a season of sprays in from a paper log has a day and a product, often with no
concentration and no clock time on the sheet. The form required both, so the only way through was
to look up a label or invent a value, and an invented value prints into the certifier packet as if
it had been observed (§ 205.103(b)).

WHAT THIS PINS
--------------
Two flags on ChemicalEvent, one rule: the flag or the value, never both, on create, on edit, in the
model's clean() and through a correction. A record whose time is not on the source record keeps
its day at noon UTC (the importer's encoding) and no reader prints that noon: the PUR leaves boxes
17-18 blank and says why, the packet and the audit CSV print "Not on the source record" where the
concentration goes, and carbon still omits the manufacturing estimate with its stated reason.
None of this reads the sibling repository.
"""

import csv
import io
import re
import uuid
from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.urls import reverse

from rest_framework.test import APIClient

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.services.verified_emission_factors import VerifiedEmissionFactors
from company.models import Company, Establishment
from history.amendments import AmendmentError, amendable_fields, apply_amendment
from history.constants import CHEMICAL_EVENT_TYPE
from history.models import ChemicalEvent, EventAmendment, History
from history.serializers import UpdateChemicalEventSerializer
from history.services import multi_target
from history.services.audit_export_service import AuditExportService
from history.services.not_on_source_record import NOT_ON_SOURCE_RECORD
from history.services.pur_export_service import PURExportService
from product.models import Parcel, Product
from users.models import User, WorksIn

NOON = datetime(2026, 4, 20, 12, tzinfo=dt_tz.utc)


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


class _PaperLog(TestCase):
    """A WA-style paper spray log keyed in for a CA block: a day, a product, nothing else."""

    def setUp(self):
        self.user = User.objects.create_user(email="paperlog@test.com", password="x")
        self.company = Company.objects.create(name="Fictional Paper Log Orchard")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(
            name="Fictional Block", company=self.company, address="1 Orchard Rd", city="Fresno", state="CA"
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

    def _spray(self, **extra):
        values = dict(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            date=datetime(2026, 4, 20, 9, 30, tzinfo=dt_tz.utc),
            commercial_name="Kocide 3000-O",
            volume_numeric=Decimal("8"),
            volume_unit="lbs",
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
                "type": "FU",
                "date": "2026-04-20T09:30",
                "commercial_name": "Kocide 3000-O",
            }
        )
        base.update(payload)
        return UpdateChemicalEventSerializer(instance=instance, data=base, partial=partial)


class ConcentrationFlagTests(_PaperLog):
    def test_the_flag_alone_is_accepted_and_stored(self):
        serializer = self._serializer({"concentration_not_recorded": True})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        event = serializer.save()
        self.assertTrue(event.concentration_not_recorded)
        self.assertFalse((event.concentration or "").strip())

    def test_the_flag_and_a_value_together_are_refused(self):
        serializer = self._serializer({"concentration_not_recorded": True, "concentration": "46.1%"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("concentration", serializer.errors)

    def test_no_flag_and_no_value_keeps_todays_behaviour(self):
        # The API never required a concentration (the form does, and keeps doing so unless the
        # box is ticked); a record with neither saves as it did before this change.
        serializer = self._serializer({})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        event = serializer.save()
        self.assertFalse(event.concentration_not_recorded)
        self.assertFalse(event.time_not_recorded)

    def test_an_edit_cannot_pair_the_flag_with_the_stored_value(self):
        event = self._spray(concentration="46.1%")
        serializer = self._serializer({"concentration_not_recorded": True}, instance=event, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("concentration", serializer.errors)

        serializer = self._serializer(
            {"concentration_not_recorded": True, "concentration": ""}, instance=event, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        event.refresh_from_db()
        self.assertTrue(event.concentration_not_recorded)
        self.assertEqual(event.concentration, "")

    def test_the_models_clean_refuses_the_pair(self):
        event = self._spray(concentration="46.1%", concentration_not_recorded=True)
        with self.assertRaises(DjangoValidationError) as caught:
            event.clean()
        self.assertIn("concentration", caught.exception.message_dict)


class TimeFlagTests(_PaperLog):
    def test_a_day_alone_is_stored_at_noon_utc_like_an_imported_row(self):
        serializer = self._serializer({"date": "2026-04-20", "time_not_recorded": True})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        event = serializer.save()
        event.refresh_from_db()
        self.assertTrue(event.time_not_recorded)
        self.assertEqual(event.date, NOON)

    def test_the_noon_placeholder_is_accepted_back_on_an_edit(self):
        serializer = self._serializer({"date": "2026-04-20T12:00", "time_not_recorded": True})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.save().date, NOON)

    def test_a_clock_time_with_the_flag_is_refused(self):
        serializer = self._serializer({"date": "2026-04-20T09:30", "time_not_recorded": True})
        self.assertFalse(serializer.is_valid())
        self.assertIn("date", serializer.errors)

    def test_ca_start_and_completion_times_with_the_flag_are_refused(self):
        serializer = self._serializer(
            {"date": "2026-04-20", "time_not_recorded": True, "application_start": "2026-04-20T06:15"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("application_start", serializer.errors)

    def test_an_edit_that_sets_only_the_flag_drops_the_stored_clock(self):
        event = self._spray()
        serializer = self._serializer({"time_not_recorded": True}, instance=event, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        event.refresh_from_db()
        self.assertEqual(event.date, NOON)

    def test_without_the_flag_the_clock_is_kept(self):
        serializer = self._serializer({"date": "2026-04-20T09:30"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.save().date, datetime(2026, 4, 20, 9, 30, tzinfo=dt_tz.utc))


class PrintedWordingTests(_PaperLog):
    def test_the_packet_log_prints_the_phrase_and_a_plain_blank_keeps_its_dash(self):
        self._spray(commercial_name="Flagged Product", concentration_not_recorded=True)
        self._spray(commercial_name="Blank Product", date=datetime(2026, 4, 21, 9, tzinfo=dt_tz.utc))
        text = _flatten(AuditExportService(self.history, certification_type="organic")._build_chemical_log())
        self.assertEqual(text.count(NOT_ON_SOURCE_RECORD), 1)
        # The sibling row with nothing entered still reads as a blank, not as the statement.
        blank_row = text.split("Blank Product", 1)[1]
        self.assertTrue(blank_row.lstrip().split(" ", 2)[1].startswith("—"), blank_row[:80])

    def test_the_audit_csv_prints_the_phrase_in_the_concentration_column(self):
        self._spray(concentration_not_recorded=True)
        self._spray(commercial_name="Blank Product", date=datetime(2026, 4, 21, 9, tzinfo=dt_tz.utc))
        raw = AuditExportService(self.history, certification_type="organic").generate_csv().getvalue()
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        header = next(r for r in rows if "Concentration / NPK" in r)
        col = header.index("Concentration / NPK")
        product_col = header.index("Product / Input")
        by_product = {r[product_col]: r[col] for r in rows[rows.index(header) + 1 :] if len(r) > col}
        self.assertEqual(by_product["Kocide 3000-O"], NOT_ON_SOURCE_RECORD)
        self.assertNotEqual(by_product["Blank Product"], NOT_ON_SOURCE_RECORD)

    def test_carbon_still_omits_manufacturing_with_its_stated_reason(self):
        event = self._spray(concentration_not_recorded=True)
        data = EventCarbonCalculator()._extract_chemical_event_data(event)
        self.assertIsNone(data["concentration"])
        breakdown = VerifiedEmissionFactors.calculate_chemical_application_emissions(
            chemical_type="FU",
            volume_liters=20.0,
            area_hectares=1.6,
            npk_content={"N": 0, "P": 0, "K": 0},
            chemical_subtype="copper_fungicide",
            concentration=data["concentration"],
        )["breakdown"]
        self.assertTrue(breakdown["manufacturing_emissions_omitted"])
        self.assertIn("concentration not provided", breakdown["manufacturing_omitted_reason"])


class PURTests(_PaperLog):
    def test_boxes_17_and_18_stay_blank_and_the_row_says_why(self):
        self._spray(date=NOON, time_not_recorded=True)
        row = PURExportService(self.est, 4, 2026).build_rows()[0]
        self.assertEqual((row["application_start"], row["application_end"]), ("", ""))
        # Still owed: the form requires a time and offers no "unknown", so the row is not ready.
        self.assertIn("application_start", row["missing"])
        self.assertIn("application_end", row["missing"])
        self.assertIn({"code": "time_not_on_source_record"}, row["flags"])
        self.assertIn("Applied on 2026-04-20.", row["notes"])
        self.assertIn("not on the source record", row["notes"])

    def test_the_filed_csv_never_carries_the_noon_placeholder(self):
        self._spray(date=NOON, time_not_recorded=True)
        service = PURExportService(self.est, 4, 2026)
        body = service.to_csv().getvalue().decode("utf-8-sig")
        self.assertNotIn("1200", body)
        self.assertNotIn("12:00", body)
        self.assertIn("Applied on 2026-04-20.", body)

    def test_an_unflagged_row_raises_no_time_flag(self):
        self._spray()
        row = PURExportService(self.est, 4, 2026).build_rows()[0]
        self.assertNotIn("time_not_on_source_record", [f["code"] for f in row["flags"]])


class CorrectionTests(_PaperLog):
    def _correct(self, event, field_name, new_value, reason="The paper log does not show it."):
        return apply_amendment(
            event=event,
            event_type=CHEMICAL_EVENT_TYPE,
            field_name=field_name,
            new_value=new_value,
            reason=reason,
            user=self.user,
        )

    def _trail(self, event):
        return {
            a.field_name: (a.original_value, a.corrected_value, a.reason)
            for a in EventAmendment.objects.filter(event_type=CHEMICAL_EVENT_TYPE, event_id=event.id)
        }

    def test_both_flags_are_correctable_fields(self):
        names = {f.name for f in amendable_fields(ChemicalEvent)}
        self.assertIn("concentration_not_recorded", names)
        self.assertIn("time_not_recorded", names)

    def test_marking_the_concentration_clears_the_invented_value_on_the_trail(self):
        event = self._spray(concentration="46.1%")
        self._correct(event, "concentration_not_recorded", "true")
        event.refresh_from_db()
        self.assertTrue(event.concentration_not_recorded)
        self.assertIsNone(event.concentration)
        trail = self._trail(event)
        self.assertEqual(trail["concentration_not_recorded"][:2], ("false", "true"))
        self.assertEqual(trail["concentration"][:2], ("46.1%", ""))
        self.assertEqual(trail["concentration"][2], trail["concentration_not_recorded"][2])

    def test_entering_a_concentration_later_clears_the_mark(self):
        event = self._spray(concentration_not_recorded=True)
        self._correct(event, "concentration", "46.1%", reason="Label photo arrived.")
        event.refresh_from_db()
        self.assertEqual(event.concentration, "46.1%")
        self.assertFalse(event.concentration_not_recorded)
        self.assertEqual(self._trail(event)["concentration_not_recorded"][:2], ("true", "false"))

    def test_marking_the_time_moves_the_day_to_the_placeholder_and_never_prints_noon(self):
        event = self._spray()
        self._correct(event, "time_not_recorded", "yes")
        event.refresh_from_db()
        self.assertTrue(event.time_not_recorded)
        self.assertEqual(event.date, NOON)
        original, corrected, _reason = self._trail(event)["date"]
        self.assertIn("09:30", original)
        self.assertEqual(corrected, "2026-04-20 (time not on the source record)")
        self.assertNotIn("12:00", corrected)

    def test_marking_the_time_clears_the_ca_start_and_completion_times(self):
        event = self._spray(application_start=datetime(2026, 4, 20, 6, 15, tzinfo=dt_tz.utc))
        self._correct(event, "time_not_recorded", "true")
        event.refresh_from_db()
        self.assertIsNone(event.application_start)
        self.assertIn("application_start", self._trail(event))

    def test_clearing_the_time_mark_alone_is_refused(self):
        event = self._spray(date=NOON, time_not_recorded=True)
        with self.assertRaises(AmendmentError):
            self._correct(event, "time_not_recorded", "false")
        event.refresh_from_db()
        self.assertTrue(event.time_not_recorded)

    def test_a_date_with_its_time_clears_the_mark_and_the_trail_never_shows_noon(self):
        event = self._spray(date=NOON, time_not_recorded=True)
        self._correct(event, "date", "2026-04-20T07:15:00+00:00", reason="Applicator's sheet found.")
        event.refresh_from_db()
        self.assertFalse(event.time_not_recorded)
        self.assertEqual(event.date, datetime(2026, 4, 20, 7, 15, tzinfo=dt_tz.utc))
        original, corrected, _ = self._trail(event)["date"]
        self.assertEqual(original, "2026-04-20 (time not on the source record)")
        self.assertIn("07:15", corrected)

    def test_a_new_day_without_a_time_keeps_the_mark_at_the_placeholder(self):
        event = self._spray(date=NOON, time_not_recorded=True)
        self._correct(event, "date", "2026-04-21")
        event.refresh_from_db()
        self.assertTrue(event.time_not_recorded)
        self.assertEqual(event.date, datetime(2026, 4, 21, 12, tzinfo=dt_tz.utc))
        self.assertNotIn("time_not_recorded", self._trail(event))

    def test_a_start_time_on_a_record_without_a_time_is_refused(self):
        event = self._spray(date=NOON, time_not_recorded=True)
        with self.assertRaises(AmendmentError):
            self._correct(event, "application_start", "2026-04-20T06:15:00+00:00")

    def test_the_correction_form_shows_the_day_not_the_placeholder(self):
        event = self._spray(date=NOON, time_not_recorded=True)
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get(
            f"/api/companies/{self.company.id}/establishments/{self.est.id}"
            f"/events/{event.id}/amend/?event_type={CHEMICAL_EVENT_TYPE}"
        )
        self.assertEqual(response.status_code, 200)
        current = {f["name"]: f["current_value"] for f in response.json()["fields"]}
        self.assertEqual(current["date"], "2026-04-20 (time not on the source record)")


class ReadersTests(_PaperLog):
    def test_the_activity_feed_row_carries_the_mark(self):
        self._spray(date=NOON, time_not_recorded=True)
        client = APIClient()
        client.force_authenticate(user=self.user)
        rows = client.get(f"/api/companies/{self.company.id}/establishments/{self.est.id}/activity-feed/").data[
            "activities"
        ]
        self.assertEqual([r["time_not_recorded"] for r in rows], [True])


class MultiParcelTests(TestCase):
    def test_both_flags_are_shared_facts_of_the_one_application(self):
        spec = multi_target.spec_for(CHEMICAL_EVENT_TYPE)
        for key in ("concentration_not_recorded", "time_not_recorded"):
            self.assertNotIn(key, spec.per_target_any(), key)
            self.assertNotIn(key, spec.refused, key)
            self.assertNotIn(key, spec.either, key)
        shared, targets = multi_target.check_envelope(
            {
                "event_type": CHEMICAL_EVENT_TYPE,
                "type": "FU",
                "date": "2026-04-20",
                "concentration_not_recorded": True,
                "time_not_recorded": True,
                "targets": [{"parcel": 1, "area_treated": "4"}, {"parcel": 2, "area_treated": "6"}],
            },
            CHEMICAL_EVENT_TYPE,
        )
        self.assertTrue(shared["concentration_not_recorded"])
        self.assertTrue(shared["time_not_recorded"])
        self.assertEqual(len(targets), 2)


class MultiParcelApiTests(_PaperLog):
    def test_one_application_on_two_blocks_writes_both_marks_on_every_record(self):
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
                "date": "2026-04-20",
                "type": "FU",
                "commercial_name": "Kocide 3000-O",
                "application_method": "air_blast",
                "volume_unit": "lbs",
                "area_unit": "acres",
                "concentration_not_recorded": True,
                "time_not_recorded": True,
                "targets": [
                    {"parcel": self.parcel.id, "area_treated": "4", "volume_applied": "8"},
                    {"parcel": south.id, "area_treated": "6", "volume_applied": "12"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        records = ChemicalEvent.objects.filter(application_group=group)
        self.assertEqual(records.count(), 2)
        for record in records:
            self.assertTrue(record.concentration_not_recorded)
            self.assertTrue(record.time_not_recorded)
            self.assertEqual(record.date, NOON)
