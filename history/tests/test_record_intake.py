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
from history.services.record_intake import COLUMNS, build_plan, execute
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
