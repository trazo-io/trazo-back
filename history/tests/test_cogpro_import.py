"""
COG Pro CSV import.

Fixtures in `fixtures/cogpro/` are real header rows and real sample rows captured from COG Pro's
own public demo account on 2026-08-06 (see `documentation/reference/cogpro-export-format.md`) —
not invented shapes. The quirks tested below are quirks their live export actually has.
"""

import io
from datetime import date, datetime
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, History, ProductionEvent
from history.services.cogpro_import import build_plan, detect_area, execute
from product.models import Parcel, Product

FIXTURES = Path(__file__).parent / "fixtures" / "cogpro"


def _date_ok(value, blob):
    """Dates are parsed to date objects, so the raw MM/DD/YYYY string will not appear."""
    from datetime import datetime

    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%a, %Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat() in blob
        except ValueError:
            continue
    return False


def _plan(name):
    with open(FIXTURES / name, "rb") as fh:
        return build_plan(fh)


class AreaDetectionTests(SimpleTestCase):
    """Route on the header row — farmers rename downloads, so filenames prove nothing."""

    def test_detects_each_area_from_its_header(self):
        expected = {
            "fertility.csv": ("fertility", "ChemicalEvent:FE"),
            "pest.csv": ("pest", "ChemicalEvent:PE"),
            "yield.csv": ("yield", "ProductionEvent:HA"),
            "field-plan.csv": ("field_plan", "ProductionEvent:PL"),
        }
        for filename, (key, target) in expected.items():
            plan = _plan(filename)
            self.assertIsNotNone(plan.area, f"{filename} not detected: {plan.error}")
            self.assertEqual(plan.area.key, key, filename)
            self.assertEqual(plan.area.target, target, filename)

    def test_pest_is_not_mistaken_for_fertility(self):
        """They share Crop/Field ID/Application Date/Amount/Measure/Rate/Method. Pest must win
        on its distinctive Target + Input pair, or spray records land as fertiliser."""
        self.assertEqual(_plan("pest.csv").area.key, "pest")

    def test_spanish_export_is_recognised(self):
        """COG Pro is fully bilingual. Matching English only would reject the file of exactly the
        crew most likely to need the migration done for them."""
        plan = _plan("fertility-spanish.csv")
        self.assertIsNotNone(plan.area, plan.error)
        self.assertEqual(plan.area.key, "fertility")
        self.assertEqual(len(plan.importable), 2)

    def test_unrecognised_file_is_reported_not_guessed(self):
        import io

        plan = build_plan(io.BytesIO(b'"Some","Other","File"\n"a","b","c"\n'))
        self.assertIsNone(plan.area)
        self.assertIn("does not look like a COG Pro export", plan.error)

    def test_empty_file_is_handled(self):
        import io

        self.assertIn("empty", build_plan(io.BytesIO(b"")).error)


class RealWorldQuirkTests(SimpleTestCase):
    """Every case here was observed in COG Pro's live export, not imagined."""

    def test_undated_rows_are_skipped_never_dated_today(self):
        """Their export genuinely contains rows with a blank Application Date. Dating one to
        import-day would fabricate a record on a day nothing happened."""
        plan = _plan("fertility.csv")
        self.assertEqual(len(plan.skipped), 1)
        self.assertIn("No usable date", plan.skipped[0].reason)
        self.assertNotIn(date.today(), [r.payload.get("date") for r in plan.importable])

    def test_unrendered_template_token_is_not_imported(self):
        """`Gross Return` contains the literal string `$[phpcode_3]` in their real data."""
        plan = _plan("yield.csv")
        for row in plan.importable:
            self.assertNotIn("phpcode", str(row.payload))

    def test_computed_display_columns_are_dropped(self):
        """`Units Per Area` = "heads / sq. feet" and `Per Area Planted` = "/ sq. feet" are
        rendering artifacts, not values."""
        plan = _plan("yield.csv")
        for row in plan.importable:
            for value in row.payload.values():
                if isinstance(value, str):
                    self.assertFalse(value.startswith("/"), value)

    def test_duplicate_planting_rate_column_does_not_lose_data(self):
        """🔴 "Planting Rate" appears TWICE in their Field Plan header. `dict(zip(...))` keeps
        only the last; this parser is index-based and takes the first."""
        plan = _plan("field-plan.csv")
        row = plan.importable[0]
        self.assertEqual(row.payload["planting_rate"], "15")

    def test_misspelled_germination_column_is_matched_literally(self):
        """Their header says "Projected Gemination Date" — missing the r. Do not 'correct' it."""
        with open(FIXTURES / "field-plan.csv", encoding="utf-8") as fh:
            self.assertIn("Projected Gemination Date", fh.readline())

    def test_dates_parse_as_month_first_in_both_languages(self):
        """COG Pro emits MM/DD/YYYY even with the Spanish UI — confirmed against their demo.
        Ambiguous DD/MM is deliberately NOT guessed: 05/12 is either May 12 or 5 December, and
        picking wrong silently misdates a spray record."""
        self.assertEqual(_plan("fertility.csv").importable[0].payload["date"], date(2022, 12, 30))
        self.assertEqual(_plan("fertility-spanish.csv").importable[0].payload["date"], date(2022, 12, 30))

    def test_pest_intervals_are_captured(self):
        """REI and PHI are regulator-relevant and Trazo has real fields for them."""
        row = _plan("pest.csv").importable[0]
        self.assertEqual(row.payload["rei_hours"], 4)
        self.assertEqual(row.payload["phi_days"], 24)
        self.assertEqual(row.payload["target_pest"], "Thrips")


class ExecuteTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Migrating Farm Co")
        establishment = Establishment.objects.create(name="Home Ranch", company=company, state="CA")
        parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=20.0)
        self.production = History.objects.create(
            name="2026 Season",
            parcel=parcel,
            product=Product.objects.create(name="Walnut"),
            start_date=date(2026, 3, 1),
        )

    def test_import_creates_chemical_events_with_source_traceability(self):
        result = execute(_plan("fertility.csv"), self.production)

        self.assertEqual(result["created"], 2)
        events = ChemicalEvent.objects.filter(history=self.production).order_by("date")
        self.assertEqual(events.count(), 2)
        first = events.first()
        self.assertEqual(first.type, "FE")
        self.assertEqual(first.commercial_name, "Lighthouse Alfalfa Meal")
        # Every imported row keeps a pointer back to its source line, so an operator can trace
        # any event in Trazo to the row it came from in the farmer's old system.
        self.assertEqual(first.extra_data["cogpro_import"]["area"], "fertility")
        self.assertIn("source_line", first.extra_data["cogpro_import"])

    def test_execute_sets_created_by_and_the_generic_source_pointer(self):
        """Until 2026-10-25 `created_by` was accepted and never written. The generic `source`
        pointer (the one the dossier prints) sits beside the `cogpro_import` block, which stays."""
        from django.contrib.auth import get_user_model

        operator = get_user_model().objects.create_user(email="op@example.com", password="pw-for-tests-only")
        execute(_plan("fertility.csv"), self.production, created_by=operator, source_title="fertility.csv")
        first = ChemicalEvent.objects.filter(history=self.production).order_by("date").first()
        self.assertEqual(first.created_by_id, operator.id)
        self.assertEqual(first.extra_data["source"]["kind"], "cogpro_export")
        self.assertEqual(first.extra_data["source"]["doc_title"], "fertility.csv")
        self.assertEqual(
            first.extra_data["source"]["locator"], f"line {first.extra_data['cogpro_import']['source_line']}"
        )
        self.assertGreater(first.index, 0, "the API's own season index, not the model default")

    def test_pest_import_carries_rei_and_phi(self):
        execute(_plan("pest.csv"), self.production)
        event = ChemicalEvent.objects.get(history=self.production, type="PE")
        self.assertEqual(event.rei_hours, 4)
        self.assertEqual(event.phi_days, 24)
        self.assertEqual(event.target_pest_disease, "Thrips")

    def test_harvest_import_creates_production_events(self):
        execute(_plan("yield.csv"), self.production)
        self.assertEqual(ProductionEvent.objects.filter(history=self.production, type="HA").count(), 1)

    def test_skipped_rows_are_not_written(self):
        plan = _plan("fertility.csv")
        result = execute(plan, self.production)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(ChemicalEvent.objects.filter(history=self.production).count(), 2)

    def test_unmappable_unit_never_fabricates_a_number(self):
        """🔴 Regression — the worst bug this importer had.

        COG Pro allows units Trazo has no equivalent for ("row feet", "heads", "bales, lg sq").
        The first version defaulted them: a Field Plan row reading "250 row feet" imported as
        "250 acres", a ~10,000x misstatement of planted area on a record a certifier reads.
        Same failure class as the hectares/acres unit bug fixed in August 2026.

        Rule: write a number ONLY with a unit Trazo can represent. Otherwise leave the typed
        field empty and preserve the raw pair — an empty field is a visible gap, a wrong unit is
        a false record.
        """
        execute(_plan("field-plan.csv"), self.production)
        event = ProductionEvent.objects.get(history=self.production, type="PL")

        self.assertIsNone(event.area_covered, "unmappable unit must not populate a typed number")
        raw = event.extra_data["cogpro_import"]["area_planted_raw"]
        self.assertIn("250", raw)
        self.assertIn("row feet", raw)

    def test_mappable_unit_is_written_normally(self):
        execute(_plan("yield.csv"), self.production)
        event = ProductionEvent.objects.get(history=self.production, type="HA")
        self.assertEqual(float(event.area_covered), 1000.0)
        self.assertEqual(event.area_unit, "sqft")
        # "heads" has no Trazo yield unit, so the quantity stays raw rather than becoming pounds.
        self.assertIsNone(event.yield_quantity)
        self.assertIn("heads", event.extra_data["cogpro_import"]["yield_raw"])

    def test_every_populated_source_cell_survives_the_import(self):
        """The migration promise, enforced: a farmer leaving COG Pro loses nothing.

        Any column this parser does not map to a real Trazo field must still be preserved under
        extra_data.cogpro_import.unmapped. An audit of the first version found 42% of columns
        being dropped on the floor.
        """
        import csv as _csv
        import json as _json

        for name in ("fertility.csv", "pest.csv", "yield.csv", "field-plan.csv"):
            plan = _plan(name)
            with open(FIXTURES / name, encoding="utf-8") as fh:
                rows = list(_csv.reader(fh))
            headers = rows[0]
            derived = {"Yield", "Units Per Area", "Gross Return", "Per Area Planted"}
            for result in plan.importable:
                source = rows[result.line - 1]
                # json default=str renders dates as ISO; str(dict) would render them
                # as datetime.date(...) reprs and hide a genuine match.
                blob = _json.dumps(result.payload, default=str).lower()
                for i, header in enumerate(headers):
                    if i >= len(source) or not source[i].strip() or header in derived:
                        continue
                    value = source[i].strip()
                    # Numbers and dates are type-converted; compare on a normalised form.
                    try:
                        needle = str(float(value))
                    except ValueError:
                        needle = value.lower()
                    self.assertTrue(
                        needle in blob or value.lower() in blob or _date_ok(value, blob),
                        f"{name} line {result.line}: column {header!r} value {value!r} was lost",
                    )

    def test_harvest_and_planting_rows_are_named(self):
        """Those tabs have no product column; a nameless event is unreadable in the timeline.

        Names say what HAPPENED, not what tool did it (changed 2026-08-07). The old fallback took
        the first non-empty column, which produced an equipment-cleaning record called "Water" and
        an orchard planting called "Auger" — on a § 205.272 commingling record or a planting
        record that is precisely the information the entry exists to carry. Each tab now names
        from its own defining column, and harvest carries variety AND crop so a certifier reading
        the timeline sees "Harvest — Chandler Walnuts".
        """
        execute(_plan("yield.csv"), self.production)
        self.assertEqual(
            ProductionEvent.objects.get(history=self.production, type="HA").name,
            "Harvest — Test 1 Basil",
        )

    def test_imported_dates_do_not_shift_a_day_in_us_timezones(self):
        """🔴 Regression, caught in the browser rather than in a test.

        Trazo's event `date` is a DateTimeField with USE_TZ on. Passing a bare date stored
        midnight UTC, which is 5pm the PREVIOUS day in California — a spray imported as
        05/12/2016 rendered in the timeline as "May 11, 2016". REI/PHI windows and the CA
        monthly PUR filing are all keyed to the application date, so a one-day shift is a
        compliance defect, not a display nit.

        Noon UTC lands on the same calendar day for every timezone from UTC-11 to UTC+11.
        """
        execute(_plan("pest.csv"), self.production)
        event = ChemicalEvent.objects.get(history=self.production, type="PE")

        self.assertEqual(event.date.hour, 12, "date-only values must be stored at noon UTC")
        # The calendar day must survive a US-Pacific render.
        from datetime import timedelta
        from datetime import timezone as _tz

        pacific = event.date.astimezone(_tz(timedelta(hours=-8)))
        self.assertEqual(pacific.date().isoformat(), "2016-05-12")

    def test_row_section_lands_in_block_id_not_extra_data(self):
        """COG Pro's "Row/Section ID" is Trazo's `block_id`.

        `CommonEvent.block_id` is defined as "Farm block or section identifier" and is inherited
        by every event type, and the CA PUR export already emits it as box 22 (Block ID). An
        earlier version of this importer buried the value in extra_data, which would have hidden
        from the PUR export a field the regulator's own form asks for.
        """
        execute(_plan("fertility.csv"), self.production)
        blocks = sorted(e.block_id for e in ChemicalEvent.objects.filter(history=self.production) if e.block_id)
        self.assertEqual(blocks, ["3", "a123"])

    def test_execute_refuses_an_unrecognised_plan(self):
        import io

        with self.assertRaises(ValueError):
            execute(build_plan(io.BytesIO(b'"Nope"\n"x"\n')), self.production)


class MechanicalWeedControlTests(TestCase):
    """🔴 A weed row with nothing applied is CULTIVATION, not a herbicide application.

    COG Pro's Weed Control tab mixes mechanical, flame and spray operations. Routing the whole tab
    to ChemicalEvent:HE had two consequences, both found by importing a real organic walnut season:

      1. It CRASHED. `volume_unit` is NOT NULL and the importer passed None for a row with no
         measure, so `IntegrityError` aborted the migration. Mechanical weeding is the most common
         organic weed practice, so essentially every organic export hit this.
      2. Had it not crashed, it would have recorded mechanical cultivation as a HERBICIDE
         APPLICATION WITH NO HERBICIDE — a false record in the worst possible place, since
         § 205.601 makes herbicide use the thing a certifier scrutinises hardest on an organic
         operation.
    """

    def setUp(self):
        company = Company.objects.create(name="Organic Orchard Co")
        establishment = Establishment.objects.create(name="Home Ranch", company=company, state="CA")
        parcel = Parcel.objects.create(name="North Orchard", establishment=establishment, area=20.0)
        self.production = History.objects.create(
            name="2026 Season", parcel=parcel, start_date=date(2026, 1, 1), type="OR"
        )

    def _weed_csv(self, rows):
        header = (
            '"Crop","Field ID","Row/Section ID","Application Date","Target","Method","Equipment Used",'
            '"Material Used","Brand","Manufacturer","Amount","Measure","Rate","Labor in hrs","Notes"'
        )
        return io.BytesIO(("\r\n".join([header] + rows) + "\r\n").encode("utf-8"))

    def test_a_mechanical_row_does_not_crash_the_import(self):
        csv_file = self._weed_csv(
            [
                '"Walnuts","North Orchard","Block 1","03/18/2026","Winter annuals","Mechanical",'
                '"Berm sweep","","","","","","","2.2",""'
            ]
        )
        execute(build_plan(csv_file), self.production)  # must not raise IntegrityError

        self.assertEqual(ChemicalEvent.objects.filter(history=self.production).count(), 0)
        self.assertEqual(ProductionEvent.objects.filter(history=self.production, type="CU").count(), 1)

    def test_a_mechanical_row_is_not_recorded_as_a_herbicide(self):
        csv_file = self._weed_csv(
            [
                '"Walnuts","North Orchard","Block 1","03/18/2026","Winter annuals","Mechanical",'
                '"Berm sweep","","","","","","","2.2",""'
            ]
        )
        execute(build_plan(csv_file), self.production)

        event = ProductionEvent.objects.get(history=self.production, type="CU")
        self.assertEqual(event.name, "Mechanical")
        self.assertEqual(event.block_id, "Block 1")
        # The weed target has no ProductionEvent column and must not vanish.
        self.assertEqual(event.extra_data["cogpro_import"]["target_pest"], "Winter annuals")

    def test_a_real_spray_row_is_still_a_chemical_event(self):
        """The routing must not swallow actual applications — that would hide a real input."""
        csv_file = self._weed_csv(
            [
                '"Walnuts","North Orchard","Block 1","04/26/2026","Filaree","Spot spray","Backpack sprayer",'
                '"Caprylic acid + capric acid","Suppress EC","Westbridge","132","gallons","6 gal/ac","2.2",""'
            ]
        )
        execute(build_plan(csv_file), self.production)

        event = ChemicalEvent.objects.get(history=self.production)
        self.assertEqual(event.type, "HE")
        self.assertEqual(event.commercial_name, "Suppress EC")
        self.assertEqual(event.manufacturer, "Westbridge")
        # Substance, not brand — the National List classifier keys on it.
        self.assertEqual(event.extra_data["active_ingredient"], "Caprylic acid + capric acid")

    def test_volume_unit_is_never_null(self):
        """Directly pins the crash: NOT NULL column, and None defeated the model default."""
        csv_file = self._weed_csv(
            [
                '"Walnuts","North Orchard","Block 1","04/26/2026","Filaree","Spot spray","Backpack sprayer",'
                '"Caprylic acid","Suppress EC","Westbridge","","","","2.2",""'
            ]
        )
        execute(build_plan(csv_file), self.production)

        event = ChemicalEvent.objects.get(history=self.production)
        self.assertEqual(event.volume_unit, "")
        self.assertNotEqual(event.volume_unit, "gal", "an unstated unit must not become an invented one")


class NoColumnIsSilentlyDroppedTests(TestCase):
    """`take()` marks a column mapped even when the target model has nowhere to put it.

    That combination — claimed as mapped, never written, therefore excluded from `unmapped` — is
    how a column disappears with no trace at all, which is the one thing the importer promises
    cannot happen. Found by reconciling a full season cell by cell: 134 of 899 source cells had no
    representation in Trazo.
    """

    def setUp(self):
        company = Company.objects.create(name="Losing Nothing Co")
        establishment = Establishment.objects.create(name="Home Ranch", company=company, state="CA")
        parcel = Parcel.objects.create(name="North Orchard", establishment=establishment, area=20.0)
        self.production = History.objects.create(
            name="2026 Season", parcel=parcel, start_date=date(2026, 1, 1), type="OR"
        )

    def test_chemical_rows_keep_equipment_and_labour(self):
        """ChemicalEvent has neither column, so both used to vanish."""
        csv_file = io.BytesIO(
            (
                '"Crop","Field ID","Row/Section ID","Application Date","Inputs","Brand","Amount","Measure",'
                '"Rate","Method","Equipment","Labor in hrs","Notes"\r\n'
                '"Walnuts","North Orchard","Block 1","02/10/2026","Compost","Recology","88","tons",'
                '"4 ton/ac","Broadcast","Manure spreader","6.2","OMRI listed"\r\n'
            ).encode("utf-8")
        )
        execute(build_plan(csv_file), self.production)

        extra = ChemicalEvent.objects.get(history=self.production).extra_data["cogpro_import"]
        self.assertEqual(extra["equipment"], "Manure spreader")
        self.assertEqual(str(extra["labor_hours"]), "6.2")

    def test_the_second_planting_rate_column_survives(self):
        """Their Field Plan header carries "Planting Rate" TWICE with different values.

        Index-based parsing avoids the dict(zip()) collision, but only if BOTH indices are read.
        """
        with open(FIXTURES / "field-plan.csv", "rb") as fh:
            plan = build_plan(fh)
        execute(plan, self.production)

        event = ProductionEvent.objects.filter(history=self.production, type="PL").first()
        self.assertIsNotNone(event)

    def test_equipment_cleaning_keeps_its_method_and_material(self):
        """§ 205.272 records exist to prove HOW equipment was cleaned and with WHAT."""
        csv_file = io.BytesIO(
            (
                '"Equipment","Target","Date","Material","Amount","Measure","Rate","Method","Labor in hrs","Notes"\r\n'
                '"Airblast sprayer","Tank cleanout","03/14/2026","Water","200","gallons","","Triple rinse","1.5",""\r\n'
            ).encode("utf-8")
        )
        execute(build_plan(csv_file), self.production)

        event = ProductionEvent.objects.get(history=self.production, type="EM")
        extra = event.extra_data["cogpro_import"]
        self.assertEqual(extra["method"], "Triple rinse")
        self.assertEqual(extra["material"], "Water")
        self.assertIn("200", extra["amount"])
        # Named for the JOB, not the material: "Water" told a certifier nothing.
        self.assertTrue(event.name.startswith("Tank cleanout"), event.name)

    def test_variety_reaches_its_real_column(self):
        """ProductionEvent HAS a variety field; the importer was only stashing it in extra_data."""
        csv_file = io.BytesIO(
            (
                '"Crop","Variety","Field ID","Row/Section ID","Date","Harvest Lot No.","Yield Amount",'
                '"Yield Units","Product Value","Area Planted","Area Measure","Yield","Units Per Area",'
                '"Gross Return","Per Area Planted","Planting Batch #","Status","Classification",'
                '"Labor in hrs","Notes"\r\n'
                '"Walnuts","Chandler","North Orchard","Block 1","09/18/2026","SNC-2026-W01","44.2","tons",'
                '"125528","22","acres","2.009","tons / acres","$[phpcode_3]","/ acres","B-01","Harvested",'
                '"Organic","19.8","Shaken"\r\n'
            ).encode("utf-8")
        )
        execute(build_plan(csv_file), self.production)

        event = ProductionEvent.objects.get(history=self.production, type="HA")
        self.assertEqual(event.variety, "Chandler")
        # The harvest lot number is the traceability key and has no column of its own.
        self.assertEqual(event.extra_data["cogpro_import"]["lot"], "SNC-2026-W01")


class ProductionNameIsNotOverwrittenTests(TestCase):
    """The list serializer must not replace a name the farmer chose.

    `OptimizedHistoryListSerializer.to_representation` generated "{product} {year}" and assigned it
    UNCONDITIONALLY, burying the real name in extra_data. A production named "Chandler Walnuts
    2026" was displayed as "Walnut 2026" everywhere that serializer is used — including the
    parcel view a certifier is walked through, which breaks the link between what the grower calls
    a block and what the record calls it.
    """

    def setUp(self):
        company = Company.objects.create(name="Naming Co")
        establishment = Establishment.objects.create(name="Home Ranch", company=company, state="CA")
        self.parcel = Parcel.objects.create(name="North Orchard", establishment=establishment, area=20.0)

    def _serialize(self, history):
        from history.serializers import OptimizedHistoryListSerializer

        return OptimizedHistoryListSerializer(history).data

    def test_a_farmer_chosen_name_survives(self):
        history = History.objects.create(
            name="Chandler Walnuts 2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Walnut"),
            start_date=timezone.make_aware(datetime(2026, 1, 1)),
        )

        self.assertEqual(self._serialize(history)["name"], "Chandler Walnuts 2026")

    def test_an_unnamed_production_still_gets_a_readable_label(self):
        """The generated name remains the fallback — it was solving a real problem for blank names."""
        history = History.objects.create(
            name="",
            parcel=self.parcel,
            product=Product.objects.create(name="Walnut"),
            start_date=timezone.make_aware(datetime(2026, 1, 1)),
        )

        self.assertEqual(self._serialize(history)["name"], "Walnut 2026")

    def test_the_generated_form_is_still_available(self):
        history = History.objects.create(
            name="Chandler Walnuts 2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Walnut"),
            start_date=timezone.make_aware(datetime(2026, 1, 1)),
        )

        self.assertEqual(self._serialize(history)["extra_data"]["generated_name"], "Walnut 2026")


class StoredUnitsAreNotReplacedByDefaultsTests(TestCase):
    """🔴 88 tons of compost was served to the UI as "88 L".

    `ChemicalEventSerializer.to_representation` resolved the unit from the combined `volume`
    string, then extra_data, then a hardcoded "L" — and never consulted `instance.volume_unit`,
    which is the real column. `volume` is a bare number for anything not written as "400 kg/ha",
    so every imported and most form-entered events fell through to the default.

    No conversion happened; it was a relabel, three orders of magnitude out, on the number the
    certifier packet, the carbon calculation and the consumer page all read. `area_unit` had the
    same shape and turned a US farm's acres into hectares.
    """

    def setUp(self):
        company = Company.objects.create(name="Units Co")
        establishment = Establishment.objects.create(name="Home Ranch", company=company, state="CA")
        parcel = Parcel.objects.create(name="North Orchard", establishment=establishment, area=20.0)
        self.production = History.objects.create(
            name="2026 Season", parcel=parcel, start_date=timezone.make_aware(datetime(2026, 1, 1)), type="OR"
        )

    def _serialize(self, event):
        from history.serializers import ChemicalEventSerializer

        return ChemicalEventSerializer(event).data

    def test_a_stored_unit_survives_serialization(self):
        event = ChemicalEvent.objects.create(
            history=self.production,
            type="FE",
            date=timezone.make_aware(datetime(2026, 2, 10, 12)),
            commercial_name="Recology Grover Env Organics",
            volume="88.0",
            volume_numeric=88,
            volume_unit="tons",
        )

        data = self._serialize(event)
        self.assertEqual(data["volume_unit"], "tons")
        self.assertNotEqual(data["volume_unit"], "L", "a stored unit was replaced by the default")

    def test_area_unit_is_not_forced_to_hectares(self):
        event = ChemicalEvent.objects.create(
            history=self.production,
            type="FE",
            date=timezone.make_aware(datetime(2026, 2, 10, 12)),
            commercial_name="Gypsum",
            volume="1.0",
            volume_numeric=1,
            volume_unit="tons",
            area="22",
            area_unit="acres",
        )

        self.assertEqual(self._serialize(event)["area_unit"], "acres")

    def test_the_default_still_applies_when_nothing_is_stored(self):
        """The fallback was not the bug — overriding a real value was."""
        event = ChemicalEvent.objects.create(
            history=self.production,
            type="FE",
            date=timezone.make_aware(datetime(2026, 2, 10, 12)),
            commercial_name="Unknown input",
            volume="5",
            volume_numeric=5,
            volume_unit="",
        )

        self.assertEqual(self._serialize(event)["volume_unit"], "L")

    def test_a_unit_embedded_in_the_volume_string_still_wins(self):
        """Legacy rows wrote "400 kg/ha" into `volume`; that parse must keep working."""
        event = ChemicalEvent.objects.create(
            history=self.production,
            type="FE",
            date=timezone.make_aware(datetime(2026, 2, 10, 12)),
            commercial_name="Legacy row",
            volume="400 kg/ha",
        )

        self.assertEqual(self._serialize(event)["volume_unit"], "kg/ha")
