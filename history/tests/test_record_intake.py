"""Operator intake: a CSV in Trazo's schema becomes records that point at the paper they came from.

The fixture is the 2026-10-01 rehearsal spray sheet (`documentation/gtm-v3/rehearsal/`) written
into the intake schema with its traps left in: a "mid May" date, an "Apr 10" date, "6 oz" with no
per-acre basis, a rate in "oz", a neighbour's spray on "fence line N". Every one of those must come
back as a named refusal, never as a record.
"""

import csv
import io
import uuid
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase

from certifications.models import NationalListSubstance
from company.models import Company, Establishment
from documents.services.filing import file_document
from history.models import ChemicalEvent, History, PestManagementEvent, ProductionEvent, SoilManagementEvent
from history.services import tank_mix
from history.services.not_on_source_record import CONCENTRATION_CONFLICT, WINDOW_CONFLICT
from history.services.record_intake import ALL_COLUMNS, COLUMNS, OPTIONAL_COLUMNS, build_plan, execute, plan_fingerprint
from history.services.record_source import SOURCE_KEY, source_line
from product.models import Parcel, Product
from subscriptions.pilot_operator import authored_records
from users.models import WorksIn

FIXTURE = Path(__file__).parent / "fixtures" / "intake" / "coldwater-bench-2026.csv"
BATCH = "3f9c0a1b2c3d"


def _dt(year, month, day):
    return datetime(year, month, day, 12, tzinfo=dt_timezone.utc)


def _csv(*rows, columns=COLUMNS):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})
    return out.getvalue()


def _all_records(farm):
    out = []
    for model in (ChemicalEvent, ProductionEvent, SoilManagementEvent, PestManagementEvent):
        out.extend(model.objects.filter(history__parcel__establishment=farm))
    return out


class IntakeFarm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Coldwater Bench Co")
        self.farm = Establishment.objects.create(name="Coldwater Bench", company=self.company, country="US", state="WA")
        self.product = Product.objects.create(name="Apple")
        self.seasons = {}
        for name in ("Block 1", "Block 2", "Block 3", "Block 4"):
            parcel = Parcel.objects.create(name=name, establishment=self.farm, area=4.0)
            season = History.objects.create(
                name=f"2026 {name}", parcel=parcel, product=self.product, start_date=_dt(2026, 1, 1)
            )
            parcel.current_history = season
            parcel.save(update_fields=["current_history"])
            self.seasons[name] = season
        self.operator = get_user_model().objects.create_user(
            email="oscar+coldwater@trazo.io",
            password="pw-for-tests-only",
            first_name="Oscar",
            last_name="Munoz (Trazo setup)",
        )
        WorksIn.objects.create(
            user=self.operator, company=self.company, role=WorksIn.COMPANY_ADMIN, is_setup_operator=True
        )
        self.doc = file_document(
            establishment=self.farm,
            source="upload",
            folder="uploads",
            title="Spray and field log 2026",
            filename="spray-and-field-log-2026.csv",
            content=b"Date,Block,What,Product\n3/14/2026,All,dormant spray,Lime sulfur\n",
            content_type="text/csv",
            created_by=self.operator,
        )
        self.assertIsNotNone(self.doc, "the source document must file; the storage fallback is broken")
        NationalListSubstance.objects.create(
            substance_name="Calcium chloride",
            substance_name_normalized="calcium chloride",
            cfr_section="205.602",
            status="prohibited",
            restriction_notes="Prohibited except as a foliar spray to treat a calcium uptake disorder.",
            annotation_kind=NationalListSubstance.ANNOTATION_CONDITION,
        )
        NationalListSubstance.objects.create(
            substance_name="Glyphosate",
            substance_name_normalized="glyphosate",
            cfr_section="205.105",
            status="prohibited",
            restriction_notes="Synthetic herbicide; not on § 205.601.",
            annotation_kind=NationalListSubstance.ANNOTATION_RATIONALE,
        )
        NationalListSubstance.objects.create(
            substance_name="Copper hydroxide",
            substance_name_normalized="copper hydroxide",
            cfr_section="205.601",
            status="allowed",
        )

    def plan(self, text):
        return build_plan(io.StringIO(text.replace("{DOC}", str(self.doc.public_id))), self.farm)

    def fixture(self):
        return self.plan(FIXTURE.read_text(encoding="utf-8"))

    def row(self, **overrides):
        base = dict(
            kind="pesticide",
            date="2026-06-03",
            parcel="Block 1",
            product="Surround WP",
            active_ingredient="Kaolin",
            rate="25",
            rate_unit="lb_ac",
            target="sunburn",
            source_doc="{DOC}",
            source_locator="sheet row 12",
        )
        base.update(overrides)
        return base

    def one(self, **overrides):
        return self.plan(_csv(self.row(**overrides)))

    def reasons(self, plan):
        return {r.line: r.reason for r in plan.skipped}


class TheRehearsalSheetTests(IntakeFarm):
    def test_the_sheet_imports_what_it_states_and_refuses_the_rest(self):
        plan = self.fixture()
        self.assertEqual(plan.error, "")
        reasons = self.reasons(plan)
        self.assertEqual(sorted(reasons), [5, 8, 9, 10, 12], reasons)
        self.assertIn("'Apr 10' is not YYYY-MM-DD", reasons[5])
        self.assertIn("'mid May' is not YYYY-MM-DD", reasons[8])
        self.assertIn("rate '6' has no rate_unit", reasons[9])
        self.assertIn("rate_unit 'oz' is not a unit Trazo stores", reasons[10])
        self.assertIn("no parcel named 'fence line N'", reasons[12])
        self.assertEqual(len(plan.importable), 15)

        result = execute(plan, self.farm, self.operator, BATCH)
        # 15 rows; "All" is four blocks, "Block 1; Block 2" two, the compost row three.
        self.assertEqual(result["created"], 26)
        records = _all_records(self.farm)
        self.assertEqual(len(records), 26)
        for record in records:
            self.assertEqual(record.created_by_id, self.operator.id)
            src = record.extra_data[SOURCE_KEY]
            self.assertEqual(src["kind"], "transcription")
            self.assertEqual(src["doc"], str(self.doc.public_id))
            self.assertEqual(src["doc_title"], "Spray and field log 2026")
            self.assertTrue(src["locator"].startswith("sheet row "))
            self.assertEqual(src["batch"], BATCH)
        # A few rows read back the way the sheet wrote them.
        harvest = ProductionEvent.objects.get(history=self.seasons["Block 1"], type="HA")
        self.assertEqual(float(harvest.yield_quantity), 212.0)
        self.assertEqual(harvest.yield_unit, "bins")
        self.assertEqual(harvest.variety, "Gala")
        unfinished = ProductionEvent.objects.get(history=self.seasons["Block 3"], type="HA")
        self.assertIsNone(unfinished.yield_quantity)
        self.assertEqual(unfinished.yield_unit, "", "no default unit on a harvest that stated no amount")
        compost = SoilManagementEvent.objects.filter(type="OM")
        self.assertEqual(compost.count(), 3)
        self.assertEqual({c.amendment_type for c in compost}, {"compost"})
        self.assertEqual(len({c.application_group for c in compost}), 1)
        self.assertEqual(ProductionEvent.objects.filter(type="IR").count(), 1)

    def test_the_operator_is_counted_as_the_author_and_never_the_producer(self):
        execute(self.fixture(), self.farm, self.operator, BATCH)
        counts = authored_records(self.operator, self.company)
        self.assertEqual(counts.get("history.ChemicalEvent.created_by"), 18)
        self.assertEqual(counts.get("history.ProductionEvent.created_by"), 5)
        self.assertEqual(counts.get("history.SoilManagementEvent.created_by"), 3)


class SchemaTests(IntakeFarm):
    def test_a_missing_column_refuses_the_file(self):
        plan = self.plan(_csv(self.row(), columns=[c for c in COLUMNS if c != "source_locator"]))
        self.assertIn("missing column(s): source_locator", plan.error)
        self.assertEqual(plan.rows, [])

    def test_an_unknown_column_refuses_the_file(self):
        plan = self.plan(_csv(self.row(), columns=list(COLUMNS) + ["acres"]))
        self.assertIn("unknown column(s): acres", plan.error)

    def test_a_column_the_kind_has_no_field_for_is_refused_not_dropped(self):
        plan = self.one(kind="harvest", product="Gala apples", rate="", rate_unit="", target="", active_ingredient="")
        self.assertIn("kind 'harvest' has no field for: product", self.reasons(plan)[2])

    def test_a_product_is_required_where_the_record_is_about_one(self):
        plan = self.one(product="")
        self.assertIn("needs a product", self.reasons(plan)[2])

    def test_an_overlong_text_is_refused_by_its_csv_column_before_the_preview(self):
        plan = self.one(concentration="x" * 61)
        self.assertIn("concentration is 61 characters and the record holds 60", self.reasons(plan)[2])
        plan = self.one(product="K" * 70)
        self.assertIn("product is 70 characters and the record holds 60", self.reasons(plan)[2])
        plan = self.one(applied_by="R" * 101)
        self.assertIn("applied_by is 101 characters and the record holds 100", self.reasons(plan)[2])
        self.assertEqual(plan.importable, [])


class DateTests(IntakeFarm):
    def test_a_fuzzy_or_us_formatted_date_is_refused_not_guessed(self):
        for text in ("mid May", "Apr 10", "3/28/26", "28-03-2026"):
            plan = self.one(date=text)
            self.assertIn(f"date {text!r} is not YYYY-MM-DD", self.reasons(plan)[2], text)

    def test_an_undated_row_waits_for_the_grower(self):
        self.assertIn("no date", self.reasons(self.one(date=""))[2])

    def test_dates_land_on_the_same_calendar_day_in_us_timezones(self):
        execute(self.one(), self.farm, self.operator, BATCH)
        event = ChemicalEvent.objects.get()
        for zone in ("America/Los_Angeles", "America/New_York", "UTC"):
            self.assertEqual(event.date.astimezone(ZoneInfo(zone)).date().isoformat(), "2026-06-03", zone)


class MeasurementTests(IntakeFarm):
    def test_a_number_without_a_unit_is_refused(self):
        plan = self.one(
            kind="harvest", product="", active_ingredient="", rate="", rate_unit="", target="", amount="212"
        )
        self.assertIn("amount '212' has no amount_unit", self.reasons(plan)[2])

    def test_a_unit_without_a_number_is_refused(self):
        plan = self.one(rate="", rate_unit="lb_ac")
        self.assertIn("rate_unit 'lb_ac' has no rate", self.reasons(plan)[2])

    def test_a_unit_outside_the_vocabulary_is_refused(self):
        plan = self.one(rate="3", rate_unit="oz")
        self.assertIn("rate_unit 'oz' is not a unit Trazo stores", self.reasons(plan)[2])

    def test_a_zero_or_negative_number_is_refused(self):
        self.assertIn("rate '-25' must be greater than 0", self.reasons(self.one(rate="-25"))[2])
        self.assertIn("rate '0' must be greater than 0", self.reasons(self.one(rate="0"))[2])

    def test_a_decimal_comma_is_refused_not_read_as_a_thousands_separator(self):
        plan = self.one(rate="2,5")
        self.assertIn("rate '2,5' has a comma", self.reasons(plan)[2])
        self.assertEqual(plan.importable, [])

    def test_a_blank_measurement_leaves_no_default_unit_behind(self):
        execute(self.one(rate="", rate_unit=""), self.farm, self.operator, BATCH)
        event = ChemicalEvent.objects.get()
        self.assertIsNone(event.volume_numeric)
        self.assertEqual(event.volume_unit, "")
        self.assertEqual(event.area_unit, "")
        self.assertEqual(event.application_rate_unit, "")


class ParcelAndSeasonTests(IntakeFarm):
    def test_all_fans_out_one_record_per_parcel_sharing_one_application_group(self):
        plan = self.one(parcel="All")
        self.assertEqual(plan.importable[0].payload["parcels"], ["Block 1", "Block 2", "Block 3", "Block 4"])
        execute(plan, self.farm, self.operator, BATCH)
        events = list(ChemicalEvent.objects.all())
        self.assertEqual(len(events), 4)
        groups = {e.application_group for e in events}
        self.assertEqual(len(groups), 1)
        self.assertIsNotNone(groups.pop())
        self.assertEqual({e.history.parcel.name for e in events}, {"Block 1", "Block 2", "Block 3", "Block 4"})

    def test_the_group_id_is_the_same_on_every_run(self):
        first = self.one(parcel="All").importable[0].payload["application_group"]
        second = self.one(parcel="All").importable[0].payload["application_group"]
        self.assertEqual(first, second)

    def test_a_per_parcel_amount_on_a_many_parcel_row_is_refused_not_copied(self):
        plan = self.one(parcel="All", amount="40", amount_unit="gal")
        self.assertIn("amount on a row covering 4 parcels would be copied to every one", self.reasons(plan)[2])
        self.assertEqual(ChemicalEvent.objects.count(), 0)

    def test_a_harvest_or_a_scouting_row_on_several_parcels_is_refused(self):
        harvest = self.one(
            kind="harvest", parcel="All", product="", active_ingredient="", rate="", rate_unit="", target=""
        )
        self.assertIn("kind 'harvest' is logged on one parcel at a time", self.reasons(harvest)[2])
        scout = self.one(
            kind="scout", parcel="Block 1; Block 2", product="", active_ingredient="", rate="", rate_unit=""
        )
        self.assertIn("kind 'scout' is logged on one parcel at a time", self.reasons(scout)[2])

    def test_a_parcel_of_another_farm_with_the_same_name_is_never_written(self):
        other = Establishment.objects.create(name="Other Orchard", company=Company.objects.create(name="Other Co"))
        other_parcel = Parcel.objects.create(name="Block 1", establishment=other, area=1.0)
        other_season = History.objects.create(name="Other 2026", parcel=other_parcel, product=self.product)
        execute(self.one(), self.farm, self.operator, BATCH)
        self.assertEqual(ChemicalEvent.objects.filter(history=self.seasons["Block 1"]).count(), 1)
        self.assertEqual(ChemicalEvent.objects.filter(history=other_season).count(), 0)

    def test_a_date_on_or_before_the_finish_date_is_refused(self):
        season = self.seasons["Block 2"]
        season.finish_date = _dt(2026, 6, 30)
        season.save(update_fields=["finish_date"])
        inside = self.one(parcel="Block 2", production=str(season.id), date="2026-06-03")
        self.assertIn("closed record", self.reasons(inside)[2])
        after = self.one(parcel="Block 2", production=str(season.id), date="2026-07-10")
        self.assertEqual(len(after.importable), 1)
        unnamed = self.one(parcel="Block 2", date="2026-07-10")
        self.assertIn("has no open production", self.reasons(unnamed)[2])

    def test_a_parcel_with_two_open_seasons_needs_the_production_named(self):
        second = History.objects.create(
            name="2026 Block 1 (replant)", parcel=self.seasons["Block 1"].parcel, product=self.product
        )
        self.assertIn("2 open productions", self.reasons(self.one())[2])
        named = self.one(production=str(second.public_id))
        self.assertEqual(named.importable[0].payload["histories"], [second.id])


class ProvenanceTests(IntakeFarm):
    def test_a_rerun_writes_only_the_rows_not_yet_recorded(self):
        execute(self.one(), self.farm, self.operator, BATCH)
        again = self.one()
        self.assertIn("already recorded as", self.reasons(again)[2])
        self.assertEqual(execute(again, self.farm, self.operator, "aaaaaaaaaaaa")["created"], 0)
        fixed = self.plan(_csv(self.row(), self.row(source_locator="sheet row 13", date="2026-06-04")))
        self.assertEqual([r.line for r in fixed.importable], [3])
        execute(fixed, self.farm, self.operator, "bbbbbbbbbbbb")
        self.assertEqual(ChemicalEvent.objects.count(), 2)

    def test_a_locator_appearing_twice_in_one_file_is_refused(self):
        plan = self.plan(_csv(self.row(), self.row(date="2026-06-04")))
        self.assertIn("appears twice in this file", self.reasons(plan)[3])

    def test_the_source_document_must_be_an_upload_on_this_farm(self):
        self.assertIn("not an uploaded document on this farm", self.reasons(self.one(source_doc=str(uuid.uuid4())))[2])
        packet = file_document(
            establishment=self.farm,
            source="packet",
            folder="exports",
            title="A packet",
            filename="packet.zip",
            content=b"zip",
            created_by=self.operator,
        )
        self.assertIn("not an uploaded document", self.reasons(self.one(source_doc=str(packet.public_id)))[2])
        elsewhere = file_document(
            establishment=Establishment.objects.create(name="Elsewhere", company=Company.objects.create(name="E")),
            source="upload",
            folder="uploads",
            title="Their sheet",
            filename="sheet.csv",
            content=b"x",
            created_by=self.operator,
        )
        self.assertIn("not an uploaded document", self.reasons(self.one(source_doc=str(elsewhere.public_id)))[2])
        self.assertIn("required", self.reasons(self.one(source_locator=""))[2])

    def test_the_source_line_names_the_typist_the_document_and_the_row(self):
        execute(self.one(), self.farm, self.operator, BATCH)
        event = ChemicalEvent.objects.get()
        self.assertEqual(
            source_line(event),
            "Transcribed by Oscar Munoz (Trazo setup) from Spray and field log 2026, sheet row 12",
        )


class NationalListPreviewTests(IntakeFarm):
    def test_a_prohibited_substance_is_named_in_the_preview_and_still_importable(self):
        plan = self.one(kind="herbicide", product="Roundup", active_ingredient="Glyphosate", target="weeds")
        row = plan.importable[0]
        self.assertTrue(row.payload["warning"])
        self.assertIn("Glyphosate, § 205.105, prohibited [exact]", row.payload["classification"])
        execute(plan, self.farm, self.operator, BATCH)
        saved = ChemicalEvent.objects.get()
        self.assertEqual(saved.national_list_substance.substance_name, "Glyphosate")
        self.assertEqual(saved.national_list_basis, "exact")

    def test_a_conditional_listing_is_not_a_warning(self):
        plan = self.one(
            kind="fertilizer", product="calcium chloride", active_ingredient="Calcium chloride", target="bitter pit"
        )
        row = plan.importable[0]
        self.assertFalse(row.payload["warning"])
        self.assertIn("allowed only for the use the listing names", row.payload["classification"])

    def test_an_unlisted_name_says_so(self):
        row = self.one(product="Surround WP", active_ingredient="Kaolin").importable[0]
        self.assertIn("no listing matched this name", row.payload["classification"])
        self.assertFalse(row.payload["warning"])

    def test_the_preview_and_the_saved_record_agree(self):
        plan = self.one(kind="fungicide", product="Kocide 3000-O", active_ingredient="Copper hydroxide")
        self.assertIn("Copper hydroxide, § 205.601, allowed [exact]", plan.importable[0].payload["classification"])
        execute(plan, self.farm, self.operator, BATCH)
        self.assertEqual(ChemicalEvent.objects.get().national_list_substance.substance_name, "Copper hydroxide")


# ------------------------------------------------------------------------------------------------
# The spray record's optional columns (overall review 2026-11, OV-RK-C05)
# ------------------------------------------------------------------------------------------------

#: Every spray column filled the way a WA orchard spray sheet states it.
SPRAY = dict(
    epa_reg_no="62719-621",
    rei_hours="4",
    phi_days="7",
    restricted_use="yes",
    applicator="Rosa Diaz",
    applicator_license="WA-12345",
    applicator_address="12 Orchard Rd, Wenatchee WA 98801",
    applicator_phone="509-555-0100",
    supplier="Wilbur-Ellis Wenatchee",
    purchase_date="2026-03-02",
    purchase_invoice="INV-2231",
    input_lot="LOT-88A",
    quantity_purchased="2.5",
    quantity_purchased_unit="gal",
    organic_basis="omri_listed",
    wind_from="NW",
    wind_speed_mph="4",
    air_temperature_f="62.5",
    carrier_volume="100",
    carrier_volume_unit="gal_per_acre",
    apparatus_plate="C12345",
    applied_by_business="yes",
    firm_name="Valley Ag Services",
    firm_address="400 Mission St, Wenatchee WA 98801",
    start_time="06:30",
    end_time="08:15",
)


class SprayColumnsTests(IntakeFarm):
    def spray(self, *rows):
        return self.plan(_csv(*rows, columns=ALL_COLUMNS))

    def spray_one(self, **overrides):
        return self.spray(self.row(**overrides))

    def refusal(self, **overrides):
        """The reason one spray row waits; failing first when the row would have been recorded."""
        plan = self.spray_one(**overrides)
        self.assertEqual(plan.importable, [], f"the row must wait: {overrides}")
        return plan.skipped[0].reason

    def test_every_spray_column_round_trips_onto_the_record(self):
        plan = self.spray_one(product="Entrust SC", active_ingredient="Spinosad", target="codling moth", **SPRAY)
        self.assertEqual(self.reasons(plan), {})
        self.assertEqual(list(plan.optional_columns), list(OPTIONAL_COLUMNS))
        execute(plan, self.farm, self.operator, BATCH)
        event = ChemicalEvent.objects.get()
        self.assertEqual(event.epa_registration_number, "62719-621")
        self.assertEqual(float(event.rei_hours), 4.0)
        self.assertEqual(float(event.phi_days), 7.0)
        self.assertTrue(event.restricted_use_pesticide)
        self.assertEqual(event.applicator_name, "Rosa Diaz")
        self.assertEqual(event.applicator_certification, "WA-12345")
        self.assertEqual(event.applicator_address, "12 Orchard Rd, Wenatchee WA 98801")
        self.assertEqual(event.applicator_phone, "509-555-0100")
        self.assertEqual(event.supplier_name, "Wilbur-Ellis Wenatchee")
        self.assertEqual(event.purchase_date.isoformat(), "2026-03-02")
        self.assertEqual(event.purchase_invoice, "INV-2231")
        self.assertEqual(event.chemical_lot_number, "LOT-88A")
        self.assertEqual(float(event.quantity_purchased), 2.5)
        self.assertEqual(event.quantity_purchased_unit, "gal")
        self.assertEqual(event.organic_approved, "omri_listed")
        self.assertEqual(event.wind_from, "NW")
        self.assertEqual(float(event.wind_speed_mph), 4.0)
        self.assertEqual(float(event.air_temperature_f), 62.5)
        self.assertEqual(float(event.carrier_volume), 100.0)
        self.assertEqual(event.carrier_volume_unit, "gal_per_acre")
        self.assertEqual(event.apparatus_license_plate, "C12345")
        self.assertTrue(event.applied_by_pcb)
        self.assertEqual(event.pcb_name, "Valley Ag Services")
        self.assertEqual(event.commercial_firm_address, "400 Mission St, Wenatchee WA 98801")
        # The stated time is the record's time and the window's start; the wall clock as stored.
        self.assertFalse(event.time_not_recorded)
        self.assertEqual(event.date, datetime(2026, 6, 3, 6, 30, tzinfo=dt_timezone.utc))
        self.assertEqual(event.application_start, datetime(2026, 6, 3, 6, 30, tzinfo=dt_timezone.utc))
        self.assertEqual(event.application_end, datetime(2026, 6, 3, 8, 15, tzinfo=dt_timezone.utc))
        self.assertFalse(event.concentration_not_recorded)
        self.assertIsNone(event.tank_mix_group)
        self.assertEqual(event.tank_mix_role, "")
        # Provenance is the importer's, unchanged: the new fields ride on a record that points at its row.
        self.assertEqual(event.extra_data[SOURCE_KEY]["locator"], "sheet row 12")
        self.assertEqual(event.extra_data[SOURCE_KEY]["batch"], BATCH)
        self.assertEqual(event.created_by_id, self.operator.id)

    def test_headers_match_without_case_or_punctuation_and_aliases_are_read(self):
        columns = list(ALL_COLUMNS)
        text = _csv(self.row(epa_reg_no="62719-621", wind_speed_mph="4", organic_basis="wsda_listed"), columns=columns)
        written = {
            "epa_reg_no": "EPA Reg. No.",
            "wind_speed_mph": "Wind speed (mph)",
            "organic_basis": "organic_approved",
        }
        header = ",".join(written.get(c, c.upper() if c == "kind" else c) for c in columns)
        plan = self.plan(header + "\n" + text.split("\n", 1)[1])
        self.assertEqual(plan.error, "")
        self.assertEqual(plan.optional_columns["epa_reg_no"], "EPA Reg. No.")
        self.assertEqual(plan.optional_columns["wind_speed_mph"], "Wind speed (mph)")
        fields = plan.importable[0].payload["fields"]
        self.assertEqual(fields["epa_registration_number"], "62719-621")
        self.assertEqual(fields["organic_approved"], "wsda_listed")

    def test_a_column_under_two_spellings_refuses_the_file(self):
        columns = list(COLUMNS) + ["rei_hours", "rei"]
        plan = self.plan(_csv(self.row(), columns=columns))
        self.assertIn("A column appears twice in the header: rei_hours (rei_hours, rei)", plan.error)

    def test_an_unknown_organic_basis_is_a_row_error_never_mapped(self):
        for text in ("OMRI", "organic", "approved", "omri listed"):
            reason = self.refusal(organic_basis=text)
            self.assertIn(f"organic_basis {text!r}: Value {text!r} is not a valid choice.", reason, text)
            self.assertIn("omri_listed", reason, "the refusal names the codes the model takes")
        # The model's own code, in any case, is the code.
        fields = self.spray_one(organic_basis="CERTIFIER_APPROVED").importable[0].payload["fields"]
        self.assertEqual(fields["organic_approved"], "certifier_approved")

    def test_a_day_only_spray_row_is_marked_time_not_on_the_source_record(self):
        # A file without any spray column: the day-only rule is not opt-in.
        execute(self.one(), self.farm, self.operator, BATCH)
        event = ChemicalEvent.objects.get()
        self.assertTrue(event.time_not_recorded)
        self.assertEqual(event.date, _dt(2026, 6, 3), "the noon placeholder, as before")
        self.assertIsNone(event.application_start)

    def test_a_spray_row_with_a_time_keeps_it_and_is_not_marked(self):
        execute(self.spray_one(start_time="14:05"), self.farm, self.operator, BATCH)
        event = ChemicalEvent.objects.get()
        self.assertFalse(event.time_not_recorded)
        self.assertEqual(event.date, datetime(2026, 6, 3, 14, 5, tzinfo=dt_timezone.utc))
        self.assertEqual(event.application_start, event.date)
        self.assertIsNone(event.application_end)

    def test_an_end_before_the_start_is_refused_and_an_equal_pair_is_not(self):
        reason = self.refusal(start_time="08:15", end_time="06:30")
        self.assertIn(
            "end_time is earlier than start_time. If the application ran past midnight, the sheet does not "
            "say which day it ended: split it into two rows or leave end_time empty.",
            reason,
        )
        plan = self.spray_one(start_time="06:30", end_time="06:30")
        self.assertEqual(plan.skipped, [])
        fields = plan.importable[0].payload["fields"]
        self.assertEqual(fields["application_start"], fields["application_end"])

    def test_a_time_and_the_not_on_record_mark_never_travel_together(self):
        reason = self.refusal(start_time="06:30", time_not_on_record="yes")
        self.assertIn(f"start_time '06:30': {WINDOW_CONFLICT}", reason)
        reason = self.refusal(time_not_on_record="no")
        self.assertIn("time_not_on_record is 'no' but the row gives no start_time", reason)
        reason = self.refusal(end_time="08:00")
        self.assertIn("end_time '08:00' has no start_time", reason)
        reason = self.refusal(start_time="6:30am")
        self.assertIn("start_time '6:30am' is not HH:MM", reason)
        # Stated explicitly, the mark on a day-only row is the same as leaving it empty.
        self.assertTrue(self.spray_one(time_not_on_record="yes").importable[0].payload["fields"]["time_not_recorded"])

    def test_concentration_not_on_record_yes_leaves_it_blank_and_flags_it(self):
        execute(self.spray_one(concentration="", concentration_not_on_record="yes"), self.farm, self.operator, BATCH)
        event = ChemicalEvent.objects.get()
        self.assertTrue(event.concentration_not_recorded)
        self.assertIsNone(event.concentration)

    def test_a_blank_concentration_stays_blank_and_unflagged_without_the_column(self):
        execute(self.spray_one(concentration=""), self.farm, self.operator, BATCH)
        event = ChemicalEvent.objects.get()
        self.assertFalse(event.concentration_not_recorded)
        self.assertIsNone(event.concentration)

    def test_a_concentration_beside_the_not_on_record_mark_is_refused_in_the_models_words(self):
        reason = self.refusal(concentration="1%", concentration_not_on_record="yes")
        self.assertIn(f"concentration '1%': {CONCENTRATION_CONFLICT}", reason)

    def test_out_of_range_wind_and_temperature_are_refused_with_the_models_message(self):
        self.assertIn(
            "wind_speed_mph '151': Ensure this value is less than or equal to 150.",
            self.refusal(wind_speed_mph="151"),
        )
        self.assertIn(
            "wind_speed_mph '-1': Ensure this value is greater than or equal to 0.",
            self.refusal(wind_speed_mph="-1"),
        )
        self.assertIn(
            "air_temperature_f '141': Ensure this value is less than or equal to 140.",
            self.refusal(air_temperature_f="141"),
        )
        self.assertIn(
            "air_temperature_f '-41': Ensure this value is greater than or equal to -40.",
            self.refusal(air_temperature_f="-41"),
        )
        self.assertIn("value must be a decimal number", self.refusal(wind_speed_mph="breezy"))
        self.assertIn("is not a valid choice", self.refusal(wind_from="NNW"))
        self.assertEqual(self.spray_one(wind_from="calm", wind_speed_mph="0").skipped, [])

    def test_the_models_cross_field_rules_refuse_the_row(self):
        reason = self.refusal(restricted_use="yes")
        self.assertIn("applicator_license: Applicator certification is required for Restricted Use", reason)
        reason = self.refusal(carrier_volume="100")
        self.assertIn("carrier_volume_unit: Pick the unit for the carrier volume.", reason)
        reason = self.refusal(rei_hours="200")
        self.assertIn("rei_hours '200': REI of 200 hours seems unusually high", reason)
        reason = self.refusal(phi_days="-1")
        self.assertIn("phi_days '-1': Pre-Harvest Interval (PHI) cannot be negative", reason)

    def test_yes_no_columns_take_yes_or_no_only(self):
        self.assertIn("restricted_use 'x' is not yes or no", self.refusal(restricted_use="x"))
        fields = self.spray_one(restricted_use="No").importable[0].payload["fields"]
        self.assertFalse(fields["restricted_use_pesticide"])

    def test_a_firm_belongs_to_an_application_made_for_hire(self):
        reason = self.refusal(firm_address="400 Mission St")
        self.assertIn("firm_address describe(s) an application made for hire; set applied_by_business to yes", reason)
        self.assertEqual(self.spray_one(applied_by_business="yes", firm_name="Valley Ag").skipped, [])

    def test_purchase_columns_follow_the_importers_date_and_pair_rules(self):
        self.assertIn("purchase_date '3/2/26' is not YYYY-MM-DD", self.refusal(purchase_date="3/2/26"))
        reason = self.refusal(quantity_purchased="2.5")
        self.assertIn("quantity_purchased '2.5' has no quantity_purchased_unit", reason)
        reason = self.refusal(quantity_purchased="2.5", quantity_purchased_unit="drums")
        self.assertIn("quantity_purchased_unit 'drums' is not a unit Trazo stores", reason)
        reason = self.refusal(quantity_purchased="2.555", quantity_purchased_unit="gal")
        self.assertIn("Ensure that there are no more than 2 decimal places.", reason)

    def test_an_overlong_spray_text_is_refused_by_its_column(self):
        reason = self.refusal(apparatus_plate="P" * 21)
        self.assertIn("apparatus_plate is 21 characters and the record holds 20", reason)

    def test_a_spray_column_on_another_kind_is_refused_not_dropped(self):
        plan = self.spray_one(
            kind="harvest", product="", active_ingredient="", rate="", rate_unit="", target="", wind_from="NW"
        )
        self.assertIn("kind 'harvest' has no field for: wind_from", self.reasons(plan)[2])

    def test_a_carrier_total_on_several_parcels_is_refused_by_the_multi_parcel_spec(self):
        plan = self.spray_one(parcel="All", carrier_volume="400", carrier_volume_unit="gal_total")
        self.assertIn("carrier_volume_unit=gal_total", self.reasons(plan)[2])
        per_acre = self.spray_one(parcel="All", carrier_volume="100", carrier_volume_unit="gal_per_acre")
        self.assertEqual(len(per_acre.importable[0].payload["parcels"]), 4)

    def test_the_fingerprint_sees_a_spray_column(self):
        self.assertNotEqual(
            plan_fingerprint(self.spray_one(wind_from="NW")), plan_fingerprint(self.spray_one(wind_from="N"))
        )


class SprayTankTests(IntakeFarm):
    def tank(self, parcel="Block 2", **shared):
        common = dict(
            kind="pesticide",
            date="2026-05-20",
            parcel=parcel,
            tank="T1",
            wind_from="NW",
            wind_speed_mph="4",
            applicator="Rosa Diaz",
            observation="2nd cover",
            **shared,
        )
        return [
            self.row(
                **{
                    **common,
                    "product": "Entrust SC",
                    "active_ingredient": "Spinosad",
                    "rate": "6",
                    "rate_unit": "fl_oz_ac",
                    "target": "codling moth",
                    "epa_reg_no": "62719-621",
                    "source_locator": "sheet row 7",
                }
            ),
            self.row(
                **{
                    **common,
                    "kind": "fungicide",
                    "product": "Kocide 3000-O",
                    "active_ingredient": "Copper hydroxide",
                    "rate": "2",
                    "rate_unit": "lb_ac",
                    "target": "fire blight",
                    "source_locator": "sheet row 8",
                }
            ),
            self.row(
                **{
                    **common,
                    "product": "Dyne-Amic",
                    "active_ingredient": "",
                    "rate": "",
                    "rate_unit": "",
                    "target": "",
                    "tank_role": "Adjuvant",
                    "source_locator": "sheet row 9",
                }
            ),
        ]

    def tank_plan(self, rows):
        return self.plan(_csv(*rows, columns=ALL_COLUMNS))

    def test_rows_sharing_a_tank_become_one_tank_in_row_order_with_their_roles(self):
        plan = self.tank_plan(self.tank())
        self.assertEqual(self.reasons(plan), {})
        execute(plan, self.farm, self.operator, BATCH)
        events = list(ChemicalEvent.objects.order_by("tank_mix_line"))
        self.assertEqual(len(events), 3)
        self.assertEqual(len({e.tank_mix_group for e in events}), 1)
        self.assertIsNotNone(events[0].tank_mix_group)
        self.assertEqual([e.tank_mix_line for e in events], [1, 2, 3])
        self.assertEqual([e.commercial_name for e in events], ["Entrust SC", "Kocide 3000-O", "Dyne-Amic"])
        self.assertEqual([e.tank_mix_role for e in events], ["product", "product", "adjuvant"])
        self.assertEqual([e.type for e in events], ["PE", "FU", "PE"])
        # Per line: the product's own pest, rate and EPA number. Shared: the pass.
        self.assertEqual([e.target_pest_disease for e in events], ["codling moth", "fire blight", None])
        self.assertEqual(events[0].epa_registration_number, "62719-621")
        self.assertIsNone(events[1].epa_registration_number)
        self.assertEqual({e.wind_from for e in events}, {"NW"})
        self.assertEqual({e.applicator_name for e in events}, {"Rosa Diaz"})
        self.assertEqual({e.time_not_recorded for e in events}, {True})
        # One parcel: no `application_group` (that means one product over several parcels).
        self.assertEqual({e.application_group for e in events}, {None})
        self.assertEqual(events[1].extra_data["active_ingredient"], "Copper hydroxide")
        # Each line still points at its own sheet row.
        self.assertEqual(
            [e.extra_data[SOURCE_KEY]["locator"] for e in events], ["sheet row 7", "sheet row 8", "sheet row 9"]
        )
        self.assertEqual(
            tank_mix.tank_cell_text(events[0]), "line 1 of 3. One tank with: Kocide 3000-O, Dyne-Amic (adjuvant)"
        )

    def test_a_tank_over_several_parcels_gives_each_line_its_own_group(self):
        plan = self.tank_plan(self.tank(parcel="Block 1; Block 2")[:2])
        self.assertEqual(self.reasons(plan), {})
        execute(plan, self.farm, self.operator, BATCH)
        events = list(ChemicalEvent.objects.all())
        self.assertEqual(len(events), 4)
        tank_id = events[0].tank_mix_group
        for line in (1, 2):
            records = [e for e in events if e.tank_mix_line == line]
            self.assertEqual({e.history.parcel.name for e in records}, {"Block 1", "Block 2"})
            self.assertEqual({e.application_group for e in records}, {tank_mix.line_application_group(tank_id, line)})

    def test_a_shared_fact_that_disagrees_refuses_every_row_of_the_tank_naming_the_column(self):
        rows = self.tank()
        rows[1]["wind_speed_mph"] = "5"
        plan = self.tank_plan(rows)
        reasons = self.reasons(plan)
        self.assertEqual(sorted(reasons), [2, 3, 4])
        for reason in reasons.values():
            self.assertIn(
                "wind_speed_mph (sheet row 7: '4', sheet row 8: '5', sheet row 9: '4')",
                reason,
            )
        rows = self.tank()
        rows[2]["observation"] = ""
        self.assertIn("observation (", self.reasons(self.tank_plan(rows))[2])
        self.assertEqual(ChemicalEvent.objects.count(), 0)

    def test_per_line_columns_may_differ_without_refusing_the_tank(self):
        rows = self.tank()
        rows[0]["organic_basis"] = "omri_listed"
        rows[1]["organic_basis"] = "wsda_listed"
        rows[1]["phi_days"] = "0"
        self.assertEqual(self.reasons(self.tank_plan(rows)), {})

    def test_a_tank_waits_whole_when_one_of_its_rows_waits(self):
        rows = self.tank()
        rows[1]["rate_unit"] = "oz"
        reasons = self.reasons(self.tank_plan(rows))
        self.assertEqual(sorted(reasons), [2, 3, 4])
        self.assertIn("rate_unit 'oz' is not a unit Trazo stores", reasons[3])
        self.assertIn("tank 'T1' is recorded whole or not at all, and these rows of it wait: sheet row 8", reasons[2])

    def test_a_tank_of_one_product_is_refused(self):
        reason = self.reasons(self.tank_plan(self.tank()[:1]))[2]
        self.assertIn("tank 'T1' has one product in this document; a tank holds 2 or more", reason)

    def test_a_tank_of_adjuvants_only_is_refused_by_the_tank_contract(self):
        rows = self.tank()[:2]
        for row in rows:
            row["tank_role"] = "adjuvant"
        reason = self.reasons(self.tank_plan(rows))[2]
        self.assertIn("A tank holds at least one product, not only adjuvants.", reason)

    def test_a_tank_role_without_a_tank_or_outside_the_choices_is_refused(self):
        self.assertIn(
            "tank_role 'adjuvant' has no tank",
            self.reasons(self.plan(_csv(self.row(tank_role="adjuvant"), columns=ALL_COLUMNS)))[2],
        )
        rows = self.tank()
        rows[2]["tank_role"] = "sticker"
        self.assertIn("tank_role 'sticker' is not one of: adjuvant, product", self.reasons(self.tank_plan(rows))[4])

    def test_a_replayed_import_writes_nothing_and_never_a_second_tank(self):
        execute(self.tank_plan(self.tank()), self.farm, self.operator, BATCH)
        again = self.tank_plan(self.tank())
        self.assertEqual(len(again.skipped), 3)
        for reason in self.reasons(again).values():
            self.assertIn("already recorded as", reason)
        self.assertEqual(execute(again, self.farm, self.operator, "aaaaaaaaaaaa")["created"], 0)
        self.assertEqual(ChemicalEvent.objects.count(), 3)
        self.assertEqual(ChemicalEvent.objects.values("tank_mix_group").distinct().count(), 1)

        # A corrected sheet that adds a product to the recorded tank does not join it or start another.
        extra = dict(self.tank()[2], product="Regulaid", tank_role="", source_locator="sheet row 10")
        plan = self.tank_plan(self.tank() + [extra])
        self.assertIn("tank 'T1' is already recorded from sheet row 7, sheet row 8, sheet row 9", self.reasons(plan)[5])
        self.assertEqual(execute(plan, self.farm, self.operator, "bbbbbbbbbbbb")["created"], 0)
        self.assertEqual(ChemicalEvent.objects.count(), 3)

    def test_the_same_tank_under_new_row_numbers_is_not_written_twice(self):
        execute(self.tank_plan(self.tank()), self.farm, self.operator, BATCH)
        renumbered = self.tank()
        for row, locator in zip(renumbered, ("row 7b", "row 8b", "row 9b")):
            row["source_locator"] = locator
        reasons = self.reasons(self.tank_plan(renumbered))
        self.assertEqual(sorted(reasons), [2, 3, 4])
        self.assertIn("tank 'T1' is already recorded", reasons[2])
        self.assertEqual(ChemicalEvent.objects.count(), 3)

    def test_a_tank_written_after_the_plan_was_built_is_not_written_again(self):
        first = self.tank_plan(self.tank())
        second = self.tank_plan(self.tank())
        execute(first, self.farm, self.operator, BATCH)
        with self.assertRaises(ValueError):
            execute(second, self.farm, self.operator, "cccccccccccc")
        self.assertEqual(ChemicalEvent.objects.count(), 3)

    def test_a_label_names_one_tank_per_document_so_another_day_under_it_disagrees(self):
        later = [dict(row, date="2026-06-02", source_locator=row["source_locator"] + "b") for row in self.tank()]
        plan = self.tank_plan(self.tank() + later)
        self.assertEqual(plan.importable, [])
        reason = self.reasons(plan)[2]
        self.assertIn("date (sheet row 7: '2026-05-20', sheet row 8: '2026-05-20'", reason)
        self.assertNotIn("start_time", reason, "a different day is said once, as the date")
        # A second label on the second day is a second tank.
        relabelled = [dict(row, tank="T2") for row in later]
        plan = self.tank_plan(self.tank() + relabelled)
        self.assertEqual(self.reasons(plan), {})
        self.assertEqual(len({row.payload["tank"]["group"] for row in plan.importable}), 2)
        self.assertEqual(plan.importable[3].payload["tank"]["line"], 1)

    def test_a_sibling_refused_for_its_own_parcel_holds_the_whole_tank_until_the_cell_is_fixed(self):
        rows = self.tank()
        rows[1]["parcel"] = "Blok 2"
        plan = self.tank_plan(rows)
        reasons = self.reasons(plan)
        self.assertEqual(sorted(reasons), [2, 3, 4])
        self.assertIn("no parcel named 'Blok 2'", reasons[3])
        self.assertIn("tank 'T1' is recorded whole or not at all, and these rows of it wait: sheet row 8", reasons[2])
        self.assertEqual(execute(plan, self.farm, self.operator, BATCH)["created"], 0)
        self.assertEqual(ChemicalEvent.objects.count(), 0)

        # The cell fixed, the re-run writes the whole tank: nothing half-written stands in its way.
        rows[1]["parcel"] = "Block 2"
        plan = self.tank_plan(rows)
        self.assertEqual(self.reasons(plan), {})
        execute(plan, self.farm, self.operator, "dddddddddddd")
        events = list(ChemicalEvent.objects.order_by("tank_mix_line"))
        self.assertEqual([e.tank_mix_line for e in events], [1, 2, 3])
        self.assertEqual([e.commercial_name for e in events], ["Entrust SC", "Kocide 3000-O", "Dyne-Amic"])
        self.assertEqual(len({e.tank_mix_group for e in events}), 1)

    def test_a_sibling_on_its_own_date_or_parcel_holds_the_whole_tank(self):
        for column, value, said in (
            ("date", "mid May", "date 'mid May' is not YYYY-MM-DD"),
            ("date", "2026-05-21", "date (sheet row 7: '2026-05-20', sheet row 8: '2026-05-21'"),
            ("parcel", "Block 3", "parcel (sheet row 7: 'Block 2', sheet row 8: 'Block 3'"),
        ):
            rows = self.tank()
            rows[1][column] = value
            plan = self.tank_plan(rows)
            self.assertEqual(plan.importable, [], (column, value))
            self.assertIn(said, " | ".join(self.reasons(plan).values()), (column, value))
        self.assertEqual(ChemicalEvent.objects.count(), 0)

    def test_the_tank_id_is_the_same_on_every_run(self):
        first = self.tank_plan(self.tank()).importable[0].payload["tank"]["group"]
        second = self.tank_plan(self.tank()).importable[0].payload["tank"]["group"]
        self.assertEqual(first, second)
