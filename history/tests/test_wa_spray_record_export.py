"""Washington pesticide application records, WAC 16-228-1320 (overall review 2026-11, OV-RK-C03).

WHAT THIS PINS
--------------
The export prints every item of WAC 16-228-1320(1), (a) to (n), labelled with its letter, for one
farm and period, and names each item the record does not hold in one of three phrases: "Not
recorded", "Not on the source record" (the operator's mark) or "Not applicable (method)" for wind
and temperature on a method (1)(e) exempts. A tank prints once with every product line. Nothing
blank is filled from elsewhere: the farm's address is never the applicator's, the noon placeholder
of a day-only record is never a start time.

The copy never says "satisfies", "compliant" or "approved": whether the department accepts the
form is its decision (WAC 16-228-1320(5)).

The door: a Compliance artifact like the CA PUR export. Refused on Starter with the same code,
refused to another company's user like the PUR, 404 for a farm outside Washington, and every
download files a dated copy in the farm's Documents.
"""

import csv
import io
import uuid
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from common.specimen import SPECIMEN_TITLE
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.services.wa_spray_record_service import HEADER_STATEMENT, ITEM_LETTERS, WASprayRecordService
from product.models import Parcel, ParcelPlannedCrop, Product
from subscriptions.testing import grant_compliance_exports
from users.models import User, WorksIn

WHEN = datetime(2026, 6, 15, 7, 0, tzinfo=dt_tz.utc)
URL = "/api/histories/wa-spray-records-export/"
PUR_URL = "/api/histories/pur-export/"

BOUNDARY = [
    {"lat": 46.6010, "lng": -120.5210},
    {"lat": 46.6010, "lng": -120.5150},
    {"lat": 46.5970, "lng": -120.5150},
    {"lat": 46.5970, "lng": -120.5210},
]


def _pdf_pages(pdf_bytes):
    from pdfminer.high_level import extract_text

    pages = []
    for index in range(100):
        text = extract_text(io.BytesIO(pdf_bytes), page_numbers=[index])
        if not text:
            break
        pages.append(text)
    return pages


def _flat(text):
    return " ".join(text.split())


class _WAFarm(TestCase):
    """A Washington orchard with one season, built for each test."""

    state = "WA"
    is_demo = False

    def setUp(self):
        self.user = User.objects.create_user(email=f"wa-{uuid.uuid4().hex[:8]}@test.com", password="x")
        self.company = Company.objects.create(
            name="Columbia Basin Fruit LLC",
            address="410 Orchard Lane",
            city="Wenatchee",
            state="WA",
            zip_code="98801",
        )
        grant_compliance_exports(self.company)
        self.farm = Establishment.objects.create(
            name="Sunrise Block Orchard", company=self.company, state=self.state, is_demo=self.is_demo
        )
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.parcel = Parcel.objects.create(name="North Orchard", establishment=self.farm, area=10.0, polygon=BOUNDARY)
        self.history = History.objects.create(
            name="2026 Apples",
            start_date=timezone.now(),
            product=Product.objects.create(name="Apples"),
            parcel=self.parcel,
        )

    def spray(self, **overrides):
        fields = dict(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            epa_registration_number="62719-621",
            date=WHEN,
            application_start=WHEN,
            application_end=WHEN.replace(hour=9, minute=30),
            volume="6",
            volume_unit="fl_oz",
            area="10",
            area_unit="acres",
            concentration="0.5 fl oz per 100 gal",
            target_pest_disease="Codling moth",
            application_method_structured="air_blast",
            wind_from="NW",
            wind_speed_mph=4,
            air_temperature_f=62,
            carrier_volume=100,
            carrier_volume_unit="gal_per_acre",
            apparatus_license_plate="WA-FARM-1234",
            applicator_name="Maria Lopez",
            applicator_certification="WSDA 12345",
            applicator_address="22 Ridge Rd, Cashmere WA 98815",
            applicator_phone="509-555-0101",
            performed_by="Jose Ramirez",
            block_id="B7",
            description="Codling moth spray",
        )
        fields.update(overrides)
        return ChemicalEvent.objects.create(**fields)

    def tank(self, lines=3):
        group = uuid.uuid4()
        names = [("Entrust SC", "product"), ("Kocide 3000-O", "product"), ("Dyne-Amic", "adjuvant")][:lines]
        return [
            self.spray(
                commercial_name=name,
                tank_mix_group=group,
                tank_mix_line=number,
                tank_mix_role=role,
                epa_registration_number=f"EPA-{number}",
            )
            for number, (name, role) in enumerate(names, start=1)
        ]

    def service(self):
        return WASprayRecordService.for_year(self.farm, 2026)

    def row(self, label, item=None):
        """`(item, text, status)` of the first pass's row with this label. Read from the built
        rows: pdfminer reads a two-column table column by column, so a row is not one string."""
        record = self.service().build()[0]
        for row in record.before + record.after:
            if row.label == label and (item is None or row.item == item):
                return row.item, row.text, row.status
        raise AssertionError(f"no row {label!r}")

    def pdf_text(self):
        return _flat(" ".join(_pdf_pages(self.service().to_pdf())))

    def client_for(self, user=None):
        client = APIClient()
        client.force_authenticate(user=user or self.user)
        return client


class TankPrintsOnceTests(_WAFarm):
    def test_a_tank_is_one_application_with_every_product_line(self):
        self.tank(3)
        summary = self.service().summary()
        self.assertEqual(summary["pass_count"], 1)
        self.assertEqual(summary["product_line_count"], 3)
        self.assertEqual(summary["passes"][0]["products"], ["Entrust SC", "Kocide 3000-O", "Dyne-Amic"])

        text = self.pdf_text()
        self.assertEqual(text.count("Application 1:"), 1)
        self.assertNotIn("Application 2:", text)
        self.assertIn("One tank, 3 products", text)
        for name, epa in (("Entrust SC", "EPA-1"), ("Kocide 3000-O", "EPA-2"), ("Dyne-Amic", "EPA-3")):
            self.assertIn(name, text)
            self.assertIn(epa, text)
        # The pass's own facts print once, not once per product.
        self.assertEqual(text.count("WA-FARM-1234"), 1)
        self.assertEqual(text.count("Maria Lopez"), 1)

    def test_two_single_sprays_are_two_applications(self):
        self.spray()
        self.spray(commercial_name="Kocide 3000-O", date=WHEN.replace(day=20))
        self.assertEqual(self.service().summary()["pass_count"], 2)

    def test_each_item_letter_is_printed(self):
        self.spray()
        text = self.pdf_text()
        for letter in ITEM_LETTERS:
            self.assertIn(f"({letter})", text, letter)
        self.assertIn("(2) Applied 2026-06-15", text)

    def test_a_fertilizer_is_not_a_pesticide_application(self):
        self.spray()
        self.spray(type=ChemicalEvent.FERTILIZER, commercial_name="Chilean nitrate")
        self.assertEqual(self.service().summary()["product_line_count"], 1)
        self.assertNotIn("Chilean nitrate", self.pdf_text())

    def test_a_commercial_application_stays_in_and_names_the_firm(self):
        """Unlike the CA PUR, the farm's WA record names the firm (item (n))."""
        self.spray(
            applied_by_pcb=True, pcb_name="Valley Ag Spray Inc.", commercial_firm_address="9 Depot St, Yakima WA"
        )
        text = self.pdf_text()
        self.assertIn("Valley Ag Spray Inc.", text)
        self.assertIn("9 Depot St, Yakima WA", text)

    def test_lines_that_disagree_on_a_shared_fact_print_each_value(self):
        first, second, _third = self.tank(3)
        ChemicalEvent.objects.filter(pk=second.pk).update(apparatus_license_plate="WA-FARM-9999")
        text = self.pdf_text()
        self.assertIn("line 1: WA-FARM-1234; line 2: WA-FARM-9999; line 3: WA-FARM-1234", text)


class OrchardReadTests(_WAFarm):
    """Orchard specimen read (2026-11-14): what a reviewer misread on Coldwater Bench's export."""

    def test_an_applicator_with_no_license_is_never_printed_as_the_licensed_applicator(self):
        """(l) asks for "the licensed applicator's full name". A crew member's profile carries a
        name and no license, and that name printed bare beside "Licensed applicator"."""
        self.spray(applicator_name="Rafael Ibarra", applicator_certification="")
        item, text, status = self.row("Licensed applicator")
        self.assertEqual(item, "l")
        self.assertEqual(text, "Rafael Ibarra (no license number on the record)")
        self.assertEqual(status, "not_recorded")
        self.assertIn("l", self.service().build()[0].blank_items())
        csv_row = self.service().csv_rows()[0]
        self.assertEqual(csv_row["l_applicator"], "Rafael Ibarra (no license number on the record)")

    def test_a_licensed_applicator_prints_as_recorded(self):
        self.spray()
        self.assertEqual(self.row("Licensed applicator")[1:], ("Maria Lopez", "value"))

    def test_one_application_on_several_blocks_names_its_siblings(self):
        """A spray logged once on four blocks is four records, so it prints four blocks each with
        the whole 07:30 to 13:00 window. Each says it is part of one application."""
        group = uuid.uuid4()
        for block in ("B1", "B2"):
            self.spray(block_id=block, application_group=group)
        self.spray(block_id="B3", date=WHEN.replace(day=20), application_start=WHEN.replace(day=20))
        passes = self.service().build()
        self.assertEqual(len(passes), 3)
        expected = (
            "Part of spray job 1: logged as one application and printed as applications 1 and 2 (North Orchard). "
            "The start and stop times are the whole job's, not this record's alone."
        )
        self.assertEqual(passes[0].notes, [expected])
        self.assertEqual(passes[1].notes, [expected])
        self.assertEqual(passes[2].notes, [])
        self.assertIn("printed as applications 1 and 2", self.pdf_text())
        self.assertIn("printed as applications 1 and 2", self.service().csv_rows()[0]["notes"])

    def test_blocks_corrected_to_different_times_drop_the_whole_window_sentence(self):
        group = uuid.uuid4()
        self.spray(block_id="B1", application_group=group)
        self.spray(block_id="B2", application_group=group, application_end=WHEN.replace(hour=11))
        note = self.service().build()[0].notes[0]
        self.assertIn("printed as applications 1 and 2", note)
        self.assertNotIn("whole job's", note)

    def test_a_block_with_no_time_on_record_drops_the_whole_window_sentence(self):
        """Review of #430: a block marked "time not on the source record" holds no window, so the
        others' shared window is not the whole job's."""
        group = uuid.uuid4()
        self.spray(block_id="B1", application_group=group)
        self.spray(block_id="B2", application_group=group)
        self.spray(block_id="B3", application_group=group, application_start=None, application_end=None)
        note = self.service().build()[0].notes[0]
        self.assertIn("printed as applications 1, 2 and 3", note)
        self.assertNotIn("whole job's", note)

    def test_blocks_corrected_to_different_days_say_so(self):
        """Review of #430: `application_group` never changes, a block's date can be corrected alone."""
        group = uuid.uuid4()
        self.spray(block_id="B1", application_group=group)
        later = WHEN + timedelta(days=1)
        self.spray(block_id="B2", application_group=group, date=later, application_start=later)
        note = self.service().build()[0].notes[0]
        self.assertIn("Part of spray job 1: logged as one application", note)
        self.assertIn("Their dates were later recorded differently", note)
        self.assertNotIn("whole job's", note)

    def test_a_tank_on_two_blocks_names_the_other_block(self):
        tank = uuid.uuid4()
        for block in ("B1", "B2"):
            for line, (name, role) in enumerate((("Entrust SC", "product"), ("Dyne-Amic", "adjuvant")), start=1):
                self.spray(
                    block_id=block,
                    commercial_name=name,
                    tank_mix_group=tank,
                    tank_mix_line=line,
                    tank_mix_role=role,
                    application_group=uuid.uuid5(tank, str(line)),
                )
        passes = self.service().build()
        self.assertEqual(len(passes), 2)
        self.assertTrue(all(p.is_tank for p in passes))
        self.assertIn("printed as applications 1 and 2", passes[0].notes[0])


class SprayJobIndexTests(_WAFarm):
    """A reviewer counted "23 applications" from 12 sheet rows: a spray logged once on four blocks
    prints once per block. The index on page one gives one row per job and the applications it
    printed as, so the count reads right without merging what WAC 16-228-1320(1)(b) locates by field."""

    def _four_blocks_and_a_tank_on_two(self):
        group = uuid.uuid4()
        for block in ("B1", "B2", "B3", "B4"):
            self.spray(block_id=block, application_group=group, commercial_name="JMS Stylet-Oil", area="5")
        tank = uuid.uuid4()
        later = WHEN + timedelta(days=5)
        for block in ("B1", "B2"):
            for line, (name, role) in enumerate((("Entrust SC", "product"), ("Dyne-Amic", "adjuvant")), start=1):
                self.spray(
                    block_id=block,
                    date=later,
                    application_start=later,
                    application_end=later + timedelta(hours=2),
                    commercial_name=name,
                    tank_mix_group=tank,
                    tank_mix_line=line,
                    tank_mix_role=role,
                    application_group=uuid.uuid5(tank, str(line)),
                )
        self.spray(block_id="B9", date=WHEN + timedelta(days=9), application_start=WHEN + timedelta(days=9))

    def test_jobs_join_the_blocks_of_one_application(self):
        self._four_blocks_and_a_tank_on_two()
        service = self.service()
        jobs = service.jobs()
        self.assertEqual(len(service.build()), 7)
        self.assertEqual([len(job.passes) for job in jobs], [4, 2, 1])
        first, tank, single = jobs
        self.assertEqual(first.pass_numbers_text(), "1, 2, 3 and 4")
        self.assertEqual(first.products(), ["JMS Stylet-Oil"])
        self.assertEqual(first.acres_text(), "20 acres")
        self.assertEqual(first.date_text(), "2026-06-15")
        self.assertEqual(tank.products(), ["Entrust SC", "Dyne-Amic"])
        self.assertEqual(tank.places(), ["North Orchard, block B1", "North Orchard, block B2"])
        self.assertEqual(single.pass_numbers_text(), "7")
        self.assertEqual(service.summary()["job_count"], 3)

    def test_the_pdf_opens_with_the_index_and_the_true_count(self):
        self._four_blocks_and_a_tank_on_two()
        text = self.pdf_text()
        self.assertIn("Spray jobs: 3, printed as 7 applications, one per parcel or block.", text)
        self.assertIn("Printed as applications", text)
        self.assertIn("1, 2, 3 and 4", text)
        self.assertLess(text.index("Spray jobs: 3"), text.index("Application 1:"))

    def test_the_csv_carries_the_job_on_every_line(self):
        self._four_blocks_and_a_tank_on_two()
        rows = self.service().csv_rows()
        self.assertEqual([r["job"] for r in rows], [1, 1, 1, 1, 2, 2, 2, 2, 3])
        self.assertEqual(WASprayRecordService.CSV_COLUMNS[1], ("job", "Spray job"))

    def test_acres_are_not_added_up_when_a_block_has_none(self):
        group = uuid.uuid4()
        self.spray(block_id="B1", application_group=group)
        self.spray(block_id="B2", application_group=group, area="", area_unit="")
        job = self.service().jobs()[0]
        self.assertEqual(job.acres_text(), "Not added up: a block's acres are not recorded in acres or hectares")

    def test_a_job_whose_blocks_were_corrected_apart_lists_each_day(self):
        group = uuid.uuid4()
        self.spray(block_id="B1", application_group=group)
        later = WHEN + timedelta(days=1)
        self.spray(block_id="B2", application_group=group, date=later, application_start=later)
        self.assertEqual(self.service().jobs()[0].date_text(), "Days differ: 2026-06-15, 2026-06-16")

    def test_single_sprays_are_one_job_each(self):
        self.spray()
        self.spray(commercial_name="Kocide 3000-O", date=WHEN.replace(day=20))
        self.assertEqual(self.service().summary()["job_count"], 2)


class BlankItemTests(_WAFarm):
    def _pass(self):
        return self.service().build()[0]

    def test_a_full_record_names_no_blank_item(self):
        self.spray()
        self.assertEqual(self._pass().blank_items(), [])
        self.assertIn("No item of (1)(a) to (1)(n) is blank on this record.", self.pdf_text())

    def test_a_missing_item_prints_not_recorded_and_is_named(self):
        self.spray(apparatus_license_plate="", applicator_phone="", target_pest_disease="")
        record = self._pass()
        self.assertEqual(record.blank_items(), ["i", "k", "l"])
        self.assertEqual(self.row("Apparatus license plate"), ("k", "Not recorded", "not_recorded"))
        self.assertEqual(self.row("Applicator phone"), ("l", "Not recorded", "not_recorded"))
        self.assertEqual(record.products[0].pests.text, "Not recorded")
        text = self.pdf_text()
        self.assertIn("(k) Apparatus license plate", text)
        self.assertIn("Not recorded", text)
        self.assertIn("Items not on this record: (i), (k), (l).", text)

    def test_the_operators_mark_prints_not_on_the_source_record(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            date=WHEN.replace(hour=12, minute=0),
            time_not_recorded=True,
            concentration_not_recorded=True,
            description="from the paper log",
        )
        text = self.pdf_text()
        self.assertIn("time not on the source record", text)
        self.assertIn("Not on the source record", text)
        # The day is kept, the noon placeholder never prints as a time.
        self.assertIn("2026-06-15", text)
        self.assertNotIn("12:00", text)
        self.assertIn("c", self._pass().blank_items())

    def test_drip_prints_wind_and_temperature_as_not_applicable_and_does_not_name_them(self):
        self.spray(application_method_structured="drip", wind_from="", wind_speed_mph=None, air_temperature_f=None)
        record = self._pass()
        self.assertNotIn("e", record.blank_items())
        self.assertEqual(self.row("Wind"), ("e", "Not applicable (Drip / fertigation)", "not_applicable"))
        self.assertEqual(self.row("Air temperature"), ("e", "Not applicable (Drip / fertigation)", "not_applicable"))
        self.assertIn("Not applicable (Drip / fertigation)", self.pdf_text())

    def test_air_blast_without_wind_names_item_e(self):
        self.spray(wind_from="", wind_speed_mph=None)
        self.assertIn("e", self._pass().blank_items())

    def test_a_carrier_volume_answers_h_when_the_concentration_is_blank(self):
        self.spray(concentration="")
        self.assertNotIn("h", self._pass().blank_items())
        ChemicalEvent.objects.all().delete()
        self.spray(concentration="", carrier_volume=None, carrier_volume_unit="")
        self.assertIn("h", self._pass().blank_items())


class NeverInventedTests(_WAFarm):
    def test_the_farms_address_never_stands_in_for_the_applicators(self):
        self.spray(applicator_address="")
        self.assertEqual(self.row("Applicator address"), ("l", "Not recorded", "not_recorded"))
        # The operation's address prints once, under (a), and nowhere else.
        self.assertEqual(self.pdf_text().count("410 Orchard Lane"), 1)

    def test_no_start_time_is_not_recorded_rather_than_the_records_clock(self):
        self.spray(application_start=None, application_end=None)
        self.assertEqual(self.row("Start time"), ("c", "Not recorded", "not_recorded"))
        self.assertEqual(self.row("Stop time"), ("c", "Not recorded", "not_recorded"))
        # The record's own `date` carries 07:00 and is never read as the start.
        self.assertNotIn("07:00", self.pdf_text())

    def test_a_per_acre_amount_worked_out_says_so(self):
        self.spray()
        self.assertIn("0.60 fl oz/acre, worked out from the total and the acres", self.pdf_text())

    def test_a_declared_rate_prints_as_recorded(self):
        self.spray(application_rate=6, application_rate_unit="fl_oz_ac")
        text = self.pdf_text()
        self.assertIn("6 fl oz/acre", text)
        self.assertNotIn("worked out", text)

    def test_an_operation_address_part_left_blank_is_named(self):
        Company.objects.filter(pk=self.company.pk).update(zip_code="")
        self.farm.refresh_from_db()
        self.spray()
        record = self.service().build()[0]
        address = next(r for r in record.before if r.item == "a" and r.label == "Address")
        self.assertIn("ZIP code not recorded", address.text)
        self.assertIn("a", record.blank_items())

    def test_location_falls_back_to_the_boundary_centre_and_says_so(self):
        self.spray()
        self.assertIn("46.599000, -120.518000 (centre of the parcel boundary drawn in Trazo)", self.pdf_text())

    def test_section_township_range_on_the_parcel_is_printed_as_written(self):
        Parcel.objects.filter(pk=self.parcel.pk).update(section_township_range="S14 T22N R20E")
        self.spray()
        text = self.pdf_text()
        self.assertIn("S14 T22N R20E (on the parcel)", text)
        self.assertNotIn("centre of the parcel boundary", text)

    def test_the_block_variety_comes_from_the_parcels_crop_list(self):
        ParcelPlannedCrop.objects.create(parcel=self.parcel, crop="Apples", variety="Honeycrisp", block_name="B7")
        self.spray()
        self.assertIn("Apples, variety Honeycrisp (block B7 on the parcel's crop list)", self.pdf_text())

    def test_the_entry_day_comes_from_the_audit_log_or_says_it_is_not_recorded(self):
        from auditlog.models import LogEntry

        event = self.spray()
        today = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date()
        self.assertEqual(self.service().build()[0].entered, today.isoformat())
        LogEntry.objects.filter(object_pk=str(event.pk)).delete()
        self.assertEqual(self.service().build()[0].entered, "entry date not recorded")


class CopyTests(_WAFarm):
    def test_the_header_states_the_departments_decision_and_nothing_stronger(self):
        self.spray()
        pages = [_flat(page) for page in _pdf_pages(self.service().to_pdf())]
        self.assertIn("Pesticide application records for Sunrise Block Orchard, 2026. " + HEADER_STATEMENT, pages[0])
        for number, page in enumerate(pages, start=1):
            self.assertIn("Whether the Washington State Department of Agriculture accepts this form", page, number)
        csv_text = self.service().to_csv().decode("utf-8-sig")
        self.assertIn(HEADER_STATEMENT, csv_text)
        for text in (" ".join(pages), csv_text):
            lowered = text.lower()
            for word in ("satisf", "complian", "approved", "certified by"):
                self.assertNotIn(word, lowered, word)

    def test_a_map_page_for_a_drawn_parcel_and_a_named_absence_for_the_rest(self):
        self.spray()
        bare = Parcel.objects.create(name="South Block", establishment=self.farm, area=4.0)
        season = History.objects.create(
            name="South", start_date=timezone.now(), product=self.history.product, parcel=bare
        )
        self.spray(history=season, block_id="", date=WHEN.replace(day=16))
        pages = [_flat(page) for page in _pdf_pages(self.service().to_pdf())]
        self.assertTrue(
            any(page.startswith("Field map: North Orchard") or "Field map: North Orchard" in page for page in pages)
        )
        self.assertIn("No parcel boundary that can be drawn is recorded in Trazo for: South Block.", " ".join(pages))
        self.assertEqual(self.service().summary()["parcels_without_map"], ["South Block"])


class ReviewFixTests(_WAFarm):
    """Review of back #413: a tank's day read like every other shared fact, map wording per
    format, and one map predicate for the row, the preview and the pages."""

    def test_lines_corrected_to_different_days_print_each_day_everywhere(self):
        _first, second, _third = self.tank(3)
        ChemicalEvent.objects.filter(pk=second.pk).update(date=WHEN.replace(day=20))
        service = self.service()
        record = service.build()[0]
        each = "line 1: 2026-06-15; line 2: 2026-06-20; line 3: 2026-06-15"
        self.assertEqual(len(service.build()), 1)
        self.assertIsNone(record.applied_on)
        self.assertEqual(self.row("Date"), ("c", each, "value"))
        self.assertIn("The lines of this tank are recorded on different days", " ".join(record.notes))
        text = self.pdf_text()
        self.assertIn(f"Application 1: {each}, North Orchard", text)
        self.assertIn(f"(2) Applied {each};", text)
        summary_pass = service.summary()["passes"][0]
        self.assertEqual(summary_pass["event_date"], "")
        self.assertEqual(summary_pass["event_days"], ["2026-06-15", "2026-06-20"])
        self.assertEqual({row["c_date"] for row in service.csv_rows()}, {each})

    def test_a_tank_on_one_day_keeps_one_day(self):
        self.tank(2)
        summary_pass = self.service().summary()["passes"][0]
        self.assertEqual((summary_pass["event_date"], summary_pass["event_days"]), ("2026-06-15", []))
        self.assertIn("Application 1: 2026-06-15, North Orchard", self.pdf_text())

    def test_the_csv_points_at_the_pdf_for_the_map_never_at_its_own_pages(self):
        self.spray()
        service = self.service()
        cell = service.csv_rows()[0]["b_map"]
        self.assertIn("in the PDF export of these records", cell)
        self.assertNotIn("pages", cell)
        self.assertNotIn("this document", cell)
        self.assertNotIn("map pages at the end of this document", service.to_csv().decode("utf-8-sig"))
        self.assertIn("on the map pages at the end of this document", self.row("Map")[1])

    def test_a_boundary_that_cannot_be_drawn_is_no_map_in_every_place(self):
        """Four copies of one point: a ring exists, the drawing refuses it
        (certifications/tests/test_parcel_map_in_packet.py, degenerate geometry)."""
        from certifications.services.parcel_map import parcel_boundary_ring, parcel_map_drawing

        Parcel.objects.filter(pk=self.parcel.pk).update(polygon={"type": "Polygon", "coordinates": [[[1.0, 2.0]] * 4]})
        self.parcel.refresh_from_db()
        self.assertIsNotNone(parcel_boundary_ring(self.parcel))
        self.assertIsNone(parcel_map_drawing(self.parcel))
        self.spray()
        service = self.service()
        self.assertEqual(
            self.row("Map"),
            ("b", "Not included: no parcel boundary that can be drawn is recorded in Trazo.", "not_recorded"),
        )
        self.assertIn("b", service.build()[0].blank_items())
        self.assertEqual(service.summary()["parcels_without_map"], ["North Orchard"])
        self.assertTrue(service.csv_rows()[0]["b_map"].startswith("Not included"))
        text = self.pdf_text()
        self.assertNotIn("Field map:", text)
        self.assertNotIn("map pages at the end", text)
        self.assertIn("No parcel boundary that can be drawn is recorded in Trazo for: North Orchard.", text)


class CsvTests(_WAFarm):
    def test_one_row_per_product_line_tied_by_the_pass_and_every_column_lettered(self):
        self.tank(3)
        self.spray(date=WHEN.replace(day=20), commercial_name="Cyd-X")
        text = self.service().to_csv().decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        header_index = next(i for i, row in enumerate(rows) if row and row[0] == "Pass")
        header = rows[header_index]
        self.assertEqual(header, [h for _k, h in WASprayRecordService.CSV_COLUMNS])
        for letter in ITEM_LETTERS:
            self.assertTrue(any(h.startswith(f"({letter})") for h in header), letter)
        body = rows[header_index + 1 :]
        self.assertEqual(len(body), 4)
        self.assertEqual([row[0] for row in body], ["1", "1", "1", "2"])
        self.assertEqual(body[2][header.index("(d) Product name")], "Dyne-Amic")
        self.assertEqual(body[2][header.index("Line in pass")], "3 (adjuvant)")


class SpecimenTests(_WAFarm):
    is_demo = True

    def test_a_fabricated_farm_is_marked_on_every_page_and_first_in_the_csv(self):
        self.spray()
        pages = _pdf_pages(self.service().to_pdf())
        self.assertTrue(pages)
        self.assertEqual([i for i, page in enumerate(pages, 1) if "SPECIMEN" not in page], [])
        self.assertIn(SPECIMEN_TITLE, _flat(pages[0]))
        first_line = self.service().to_csv().decode("utf-8-sig").splitlines()[0]
        self.assertIn(SPECIMEN_TITLE, first_line)


class RealFarmUnmarkedTests(_WAFarm):
    def test_a_real_farm_is_not_marked(self):
        self.spray()
        self.assertNotIn("SPECIMEN", self.pdf_text())
        self.assertNotIn("SPECIMEN", self.service().to_csv().decode("utf-8-sig"))


class DoorTests(_WAFarm):
    def test_compliance_is_served_the_preview_and_both_files(self):
        self.spray()
        client = self.client_for()
        preview = client.get(URL, {"establishment_id": self.farm.id, "year": 2026})
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.json()["pass_count"], 1)
        pdf = client.get(URL, {"establishment_id": self.farm.id, "year": 2026, "export_format": "pdf"})
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(pdf.streaming_content).startswith(b"%PDF"))
        csv_response = client.get(URL, {"establishment_id": self.farm.id, "year": 2026, "export_format": "csv"})
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response["Content-Type"])

    def test_a_date_range_narrows_the_period(self):
        self.spray()
        self.spray(date=WHEN.replace(month=9), commercial_name="Cyd-X")
        body = self.client_for().get(
            URL, {"establishment_id": self.farm.id, "start": "2026-09-01", "end": "2026-09-30"}
        )
        self.assertEqual(body.json()["pass_count"], 1)
        self.assertEqual(body.json()["passes"][0]["products"], ["Cyd-X"])
        bad = self.client_for().get(URL, {"establishment_id": self.farm.id, "start": "2026-09-30", "end": "2026-09-01"})
        self.assertEqual(bad.status_code, 400)

    def test_every_download_files_a_dated_copy_in_documents(self):
        from documents.models import GeneratedDocument

        self.spray()
        client = self.client_for()
        client.get(URL, {"establishment_id": self.farm.id, "year": 2026, "export_format": "pdf"})
        client.get(URL, {"establishment_id": self.farm.id, "year": 2026, "export_format": "csv"})
        filed = GeneratedDocument.objects.filter(establishment=self.farm, source="wa_spray_records").order_by("pk")
        self.assertEqual([d.content_type for d in filed], ["application/pdf", "text/csv"])
        self.assertTrue(all(d.folder == "exports" for d in filed))
        self.assertEqual(filed[0].title, "Washington pesticide application records, 2026")
        self.assertEqual(filed[0].get_source_display(), "Washington pesticide application records")

    def test_an_empty_period_files_nothing(self):
        from documents.models import GeneratedDocument

        response = self.client_for().get(URL, {"establishment_id": self.farm.id, "year": 2025, "export_format": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GeneratedDocument.objects.filter(establishment=self.farm).exists())

    def test_another_companys_user_is_refused_like_the_pur_export(self):
        from documents.models import GeneratedDocument

        self.spray()
        outsider = User.objects.create_user(email="outsider@test.com", password="x")
        other = Company.objects.create(name="Other Orchard Co")
        grant_compliance_exports(other)
        WorksIn.objects.create(user=outsider, company=other, role=WorksIn.COMPANY_ADMIN)
        response = self.client_for(outsider).get(
            URL, {"establishment_id": self.farm.id, "year": 2026, "export_format": "pdf"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data, {"error": "Access denied"})
        # The PUR's answer to the same outsider, on a California farm of the same company.
        ca_farm = Establishment.objects.create(name="Delano Block", company=self.company, state="CA")
        pur = self.client_for(outsider).get(PUR_URL, {"establishment_id": ca_farm.id, "month": 6, "year": 2026})
        self.assertEqual((pur.status_code, pur.data), (response.status_code, response.data))
        self.assertFalse(GeneratedDocument.objects.filter(establishment=self.farm).exists())

    def test_a_farm_outside_washington_gets_404(self):
        ca_farm = Establishment.objects.create(name="Delano Block", company=self.company, state="CA")
        response = self.client_for().get(URL, {"establishment_id": ca_farm.id, "year": 2026})
        self.assertEqual(response.status_code, 404)


class PlanGateTests(TestCase):
    """Starter refused with the PUR's code; Compliance not refused. A real Starter plan, from the
    seeder, so the refusal is the plan's and not a missing subscription's."""

    @classmethod
    def setUpTestData(cls):
        from subscriptions.models import Plan, Subscription

        call_command("create_plans", verbosity=0)

        def _farm(slug, email, state="WA"):
            user = User.objects.create_user(email=email, password="x")
            company = Company.objects.create(name=f"{slug} co")
            Subscription.objects.create(
                company=company,
                plan=Plan.objects.get(slug=slug),
                status="active",
                current_period_start=timezone.now(),
                current_period_end=timezone.now() + timedelta(days=30),
            )
            WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
            return user, Establishment.objects.create(name=f"{slug} farm", company=company, state=state)

        cls.starter_user, cls.starter_farm = _farm("starter", "wa-starter@test.com")
        cls.paid_user, cls.paid_farm = _farm("compliance-yearly", "wa-paid@test.com")

    def _get(self, user, farm, **params):
        client = APIClient()
        client.force_authenticate(user=user)
        return client.get(URL, {"establishment_id": farm.id, "year": 2026, **params})

    def test_starter_is_refused_with_the_compliance_code(self):
        for export_format in ("json", "pdf", "csv"):
            response = self._get(self.starter_user, self.starter_farm, export_format=export_format)
            self.assertEqual(response.status_code, 403, export_format)
            self.assertEqual(response.data.get("detail").code, "compliance_exports_required")

    def test_compliance_is_not_refused(self):
        response = self._get(self.paid_user, self.paid_farm)
        self.assertEqual(response.status_code, 200, getattr(response, "data", None))

    def test_a_starter_farm_outside_washington_is_told_it_does_not_apply_not_to_pay(self):
        ca_farm = Establishment.objects.create(name="Starter CA", company=self.starter_farm.company, state="CA")
        self.assertEqual(self._get(self.starter_user, ca_farm).status_code, 404)
