"""The Calapooia fixture must still describe the models it is loaded into.

WHY THIS EXISTS
---------------
`seed_calapooia_bend` rebuilds the deepest dataset Trazo has — 6 parcels, 12 seasons, 512
events, 3 OSP versions — from a machine-extracted JSON fixture. The farm is the depth demo and
the artifact the certifier-packet work was validated against.

A fixture is data, so nothing about it moves when a model does. Rename a column, drop a field,
change an app label, and the fixture goes on containing the old name until somebody runs the
command and reads a traceback — which, for a demo farm, is likely to be minutes before it is
needed. That already happened once during development: `source_template` points at
`carbon.EventTemplate`, not `history.EventTemplate`, and the command failed at run time with
LookupError.

So this walks every key in the fixture and asserts the target model still has somewhere to put
it. It is fast because it touches no database — it compares names, which is exactly the thing
that drifts.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not run the seeder. That writes 512 events and fires the carbon signals on every one,
and a test that slow gets skipped, which is worse than not having it. Fidelity of the OUTPUT is
verified by rebuilding into a clean database and diffing the certifier packet against the
source — DOCUMENTED 15 = 15, GAP 2 = 2, with the single remaining difference being the
rehearsal's own audit trail, which must not be reproduced.
"""

import json
import re
from pathlib import Path

from django.apps import apps
from django.test import SimpleTestCase

# The loader's own type-marker decoder. Imported rather than reimplemented: a guard that
# decodes differently from the seeder is testing a document nobody loads.
from history.management.commands.seed_calapooia_bend import _decode

FIXTURE = Path(apps.get_app_config("history").path) / "management" / "commands" / "_calapooia_bend_data.json"

#: Fixture section -> the model its rows are loaded into.
SECTION_MODEL = {
    "establishment": ("company", "Establishment"),
    "parcels": ("product", "Parcel"),
    "seasons": ("history", "History"),
    "certifications": ("certifications", "Certification"),
    "post_harvest_facilities": ("certifications", "PostHarvestFacility"),
    "production_equipment": ("certifications", "ProductionEquipment"),
    "osps": ("certifications", "OrganicSystemPlan"),
    "annual_updates": ("certifications", "OSPAnnualUpdate"),
    "annual_update_corrections": ("certifications", "OSPAnnualUpdate"),
    "draft_annual_updates": ("certifications", "OSPAnnualUpdate"),
    "plan_forks": ("certifications", "OrganicSystemPlan"),
    "approved_input_changes": ("certifications", "ApprovedInputChangeLog"),
    "osp_change_notifications": ("certifications", "OSPChangeNotification"),
    "parcel_crop_history": ("product", "ParcelCropHistory"),
    "sales_records": ("history", "SalesRecord"),
    "production_plan_items": ("history", "ProductionPlanItem"),
    "history_scans": ("history", "HistoryScan"),
    "event_amendments": ("history", "EventAmendment"),
}

EVENT_MODELS = [
    "ChemicalEvent",
    "ProductionEvent",
    "SoilManagementEvent",
    "PestManagementEvent",
    "GeneralEvent",
    "BusinessEvent",
    "WeatherEvent",
]

#: Keys the loader consumes itself rather than assigning to a column.
STRUCTURAL = {"events", "post_harvest_facilities"}


def _writable_names(model):
    """Every name the seeder may pass to `Model.objects.create()`."""
    names = set()
    for f in model._meta.get_fields():
        if f.auto_created and not f.concrete:
            continue
        names.add(f.name)
        if getattr(f, "attname", None):
            names.add(f.attname)
    return names


class CalapooiaFixtureIntegrityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data = json.loads(FIXTURE.read_text())

    def test_fixture_is_present_and_populated(self):
        """Guards the guard: every assertion below passes vacuously on an empty fixture."""
        self.assertTrue(FIXTURE.exists(), f"missing fixture: {FIXTURE}")
        self.assertEqual(len(self.data["parcels"]), 6)
        self.assertEqual(len(self.data["seasons"]), 12)
        events = sum(len(rows) for s in self.data["seasons"] for rows in s["events"].values())
        # 513 since run 7 (2026-10-04): compost turns 4 and 5 recorded as their own dated event.
        # 512 since 2026-10-31: Home Field West's second 2026 sawdust top-dress, a day after the first
        # from another mill, was a duplicate (packet page review).
        self.assertEqual(events, 512, "the fixture no longer holds the farm it was extracted from")
        self.assertEqual(len(self.data["osps"]), 3)

    def test_every_top_level_key_maps_to_a_real_field(self):
        problems = []
        for section, (app_label, model_name) in SECTION_MODEL.items():
            rows = self.data.get(section)
            if rows is None:
                problems.append(f"{section}: section missing from fixture")
                continue
            model = apps.get_model(app_label, model_name)
            writable = _writable_names(model)
            for row in rows if isinstance(rows, list) else [rows]:
                for key in row:
                    if key.startswith(("_", "#", "@", "~")) or key in STRUCTURAL:
                        continue
                    if key not in writable:
                        problems.append(f"{section}.{key} is not a field on {model_name}")
        self.assertEqual(sorted(set(problems)), [], "fixture has drifted from the models")

    def test_every_event_key_maps_to_a_real_field(self):
        problems = []
        for season in self.data["seasons"]:
            for model_name, rows in season["events"].items():
                self.assertIn(model_name, EVENT_MODELS, f"unknown event model {model_name}")
                writable = _writable_names(apps.get_model("history", model_name))
                for row in rows:
                    for key in row:
                        if key.startswith(("_", "#", "@", "~")):
                            continue
                        if key not in writable:
                            problems.append(f"{model_name}.{key}")
        self.assertEqual(sorted(set(problems)), [], "event fixture has drifted from the models")

    def test_every_event_row_would_survive_its_own_write_serializer(self):
        """The strongest form of the question above: could a farmer have entered this?

        The choices check catches a bad VALUE. This catches a missing one — a field the write
        serializer requires that the fixture never filled. Five of the farm's six cultural-control
        events had no `cultural_practice`, the § 205.206(a) evidence, because the rule was added
        to `UpdatePestManagementEventSerializer` after the shell script wrote the rows; the packet
        printed "Practice: --" under a § 205.206(a) heading on all five.

        Runs each row through the SAME serializer POST /api/events/ selects, so any rule added
        there — cross-field, conditional, or a new required field — is enforced against the demo
        farm from the moment it lands. Relations are dropped: `history` and `album` are resolved
        by the loader, and this must stay a no-database test.
        """
        from history import serializers as hs

        WRITE_SERIALIZER = {
            "ChemicalEvent": hs.UpdateChemicalEventSerializer,
            "ProductionEvent": hs.UpdateProductionEventSerializer,
            "SoilManagementEvent": hs.UpdateSoilManagementEventSerializer,
            "PestManagementEvent": hs.UpdatePestManagementEventSerializer,
            "GeneralEvent": hs.UpdateGeneralEventSerializer,
            "BusinessEvent": hs.UpdateBusinessEventSerializer,
            "WeatherEvent": hs.UpdateWeatherEventSerializer,
        }
        problems = []
        checked = 0
        for season in self.data["seasons"]:
            for model_name, rows in season["events"].items():
                serializer_cls = WRITE_SERIALIZER[model_name]
                writable = {name for name, field in serializer_cls().fields.items() if not field.read_only} - {
                    "history",
                    "album",
                }
                for row in rows:
                    payload = {
                        k: _decode(v)
                        for k, v in row.items()
                        if k in writable and not k.startswith(("_", "#", "@", "~"))
                    }
                    serializer = serializer_cls(data=payload)
                    checked += 1
                    if not serializer.is_valid():
                        problems.append(f"{model_name} {row.get('date')}: {dict(serializer.errors)}")
        self.assertEqual(checked, 512, "not every event row was checked")
        self.assertEqual(
            problems[:10],
            [],
            f"{len(problems)} fixture events would be REJECTED by the endpoint that is "
            "supposed to have created them",
        )

    def test_every_choice_field_holds_a_value_the_api_would_accept(self):
        """A demo farm must be reproducible through the product that shows it.

        The fixture was machine-extracted from a database whose rows were written by an ad-hoc
        shell script — straight through the ORM, which does not run `choices` validation. So it
        accumulated 452 values no serializer would take: LABELS where the code belongs
        ("Farmer / Farm Staff" for `farmer`), free text in an enum ("flail mower"), near-miss
        codes ("mi" for `miles`, "well" for `well_groundwater`, "lbs" for `lb`), and one value
        belonging to a sibling field ("inspected" in `transport_cleaning_method`).

        That matters twice over. A record the API refuses is a record no farmer could have
        entered, so the farm we put in front of certifiers demonstrates a product that cannot
        produce it. And the packet renders unknown codes literally — Calapooia's printed
        "surface_water" (unrecognised value - not in the current form)" three times in one
        submission.

        Found 2026-08-22 by replaying the farm's own 2025 records back through POST /api/events/
        while simulating the following season: 16 of the first 60 re-logged records were
        rejected by the product that had stored them.
        """
        from django.apps import apps as _apps

        def _bad(model, rows):
            fields = {
                f.name: {c[0] for c in f.choices}
                for f in model._meta.get_fields()
                if getattr(f, "concrete", False) and getattr(f, "choices", None)
            }
            for row in rows:
                for name, valid in fields.items():
                    value = row.get(name)
                    if value in (None, "") or not isinstance(value, str):
                        continue
                    if value not in valid:
                        yield f"{model.__name__}.{name} = {value!r}"

        problems = []
        for section, (app_label, model_name) in SECTION_MODEL.items():
            rows = self.data.get(section) or []
            rows = rows if isinstance(rows, list) else [rows]
            problems += list(_bad(_apps.get_model(app_label, model_name), rows))
        for season in self.data["seasons"]:
            for model_name, rows in season["events"].items():
                problems += list(_bad(_apps.get_model("history", model_name), rows))

        self.assertEqual(
            sorted(set(problems)),
            [],
            "the fixture holds values the model's own `choices` reject — the API would refuse "
            "these records, so no farmer could have entered them",
        )

    def test_recorded_transport_inspections_actually_print(self):
        """A finding the farm recorded must reach the packet, not be dropped for its shape.

        `SalesRecord.transport_inspected_free_of` is a JSONField whose contract is a LIST of
        codes, and `transport_inspection_display()` returns "" for anything that is not a list —
        deliberately, so a malformed value cannot be paraphrased into an attestation nobody
        made. The fixture held the codes as one comma-joined STRING, so all 15 of Calapooia's
        sales printed no "inspected and found free of" line at all, even though the operation
        had recorded three findings on every load. JSONField accepts any JSON, so nothing
        upstream objected; the frontend has always sent a real array.

        Asserting on the rendered line rather than the type is deliberate: it is the packet
        output, not the column, that a certifier reads.
        """
        from history.models import SalesRecord

        blank = []
        for row in self.data["sales_records"]:
            value = row.get("transport_inspected_free_of")
            if not value:
                continue
            rendered = SalesRecord(transport_inspected_free_of=value).transport_inspection_display()
            if not rendered:
                blank.append(f"{row.get('invoice_number')}: {value!r}")
        self.assertEqual(blank, [], "sales records carry inspection findings that render as nothing")

    def test_relation_markers_point_at_relations_that_exist(self):
        """`#name` and `@name` must still BE relations, and `~name` still a many-to-many.

        A field that stops being a relation is the quiet version of this failure: the loader
        would pass an integer id straight into a plain column and the row would save.
        """
        problems = []
        checks = [(SECTION_MODEL[s], self.data.get(s, [])) for s in SECTION_MODEL]
        checks += [
            (("history", m), [r for s in self.data["seasons"] for r in s["events"].get(m, [])]) for m in EVENT_MODELS
        ]
        for (app_label, model_name), rows in checks:
            model = apps.get_model(app_label, model_name)
            by_name = {f.name: f for f in model._meta.get_fields()}
            for row in rows if isinstance(rows, list) else [rows]:
                for key in row:
                    if not key.startswith(("#", "@", "~")):
                        continue
                    name = key[1:]
                    field = by_name.get(name)
                    if field is None:
                        problems.append(f"{model_name}.{name} no longer exists")
                    elif key.startswith("~") and not field.many_to_many:
                        problems.append(f"{model_name}.{name} is no longer a many-to-many")
                    elif key.startswith(("#", "@")) and not (field.many_to_one or field.one_to_one):
                        problems.append(f"{model_name}.{name} is no longer a foreign key")
        self.assertEqual(sorted(set(problems)), [], "fixture relation markers have drifted")

    def test_derived_records_are_not_in_the_fixture(self):
        """CarbonEntry and USDAComplianceRecord are rebuilt by signals as the events are written.

        Carrying them would double every carbon figure on the farm. Verified against the source:
        the rebuild lands on 333 of each without either being seeded.
        """
        for banned in ("carbon_entries", "usda_compliance_records"):
            self.assertNotIn(banned, self.data)

    def test_no_real_certifier_name_survives_substitution(self):
        """The seeder replaces real organisations; this pins that the list still covers the data.

        The rehearsal named Oregon Tilth Certified Organic — a USDA-accredited agent that is also
        on the certifier outreach ladder — plus two real Oregon handlers. Naming a real ACA as
        certifying a farm that does not exist is the one thing `seed_showcase_walnut_farm`
        singles out, and the risk is sharper here because this packet is meant to be shown.
        """
        from history.management.commands.seed_calapooia_bend import _substitute

        cleaned = json.dumps(_substitute(self.data, enabled=True))
        for real in ("Oregon Tilth", "OTCO", "Organically Grown Company", "Willamette Valley Fruit"):
            self.assertNotIn(real, cleaned, f"{real!r} survives the substitution")


def _strings(value):
    """Every string inside a fixture value, recursively."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


class CalapooiaNarrativeConsistencyTests(SimpleTestCase):
    """The specimen must not contradict itself (OSP alignment audit 2026-10, T28).

    Two contradictions a reviewer found in the packet: narratives saying there was "no
    conventional production anywhere" on a farm whose G6.0 sells its buffer-row fruit as
    conventional process fruit, and onion "sets" typed into the annual-seedlings answer for a
    material the farm's own planting records describe as cell-tray transplants. Both are
    checked against the fixture's own rows, so a later edit that re-introduces either fails
    here rather than in front of a certifier.
    """

    #: Farm-wide claims that no conventional product exists. The narrower statements the
    #: fixture now makes ("the shed is organic-only", "buffer-row fruit never enters the
    #: shed") are not caught: they are true on this farm.
    BLANKET_CLAIM = re.compile(
        r"no conventional (production|product|crop)\b|organic-only on this farm\W+no conventional",
        re.IGNORECASE,
    )
    #: Planting-stock forms (7 CFR 205.2 "planting stock") that do not belong in an answer
    #: about annual seedlings.
    STOCK_TERMS = re.compile(r"\b(onion )?sets\b|\bbulbs?\b|\btubers?\b|\bcuttings?\b|\bcrowns?\b", re.IGNORECASE)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data = json.loads(FIXTURE.read_text())

    @staticmethod
    def _sells_buffer_fruit_conventional(osp) -> bool:
        answers = osp["module_responses"]["modules"].get("g6_0_production", {}).get("answers", {})
        strategies = (answers.get("buffer_strategies") or {}).get("value") or []
        return "buffer_sold_different_buyer" in strategies

    def test_the_guard_reads_a_version_that_sells_buffer_fruit(self):
        """Guards the guard: with no such version, the claim check below passes vacuously."""
        self.assertTrue(any(self._sells_buffer_fruit_conventional(o) for o in self.data["osps"]))

    def test_no_version_claims_no_conventional_production_while_selling_buffer_fruit(self):
        problems = []
        for osp in self.data["osps"]:
            if not self._sells_buffer_fruit_conventional(osp):
                continue
            for text in _strings({"sections": osp["sections"], "modules": osp["module_responses"]}):
                for m in self.BLANKET_CLAIM.finditer(text):
                    problems.append(f"v{osp['version_number']}: ...{text[max(0, m.start() - 60):m.end() + 40]}...")
        self.assertEqual(sorted(set(problems)), [], "a narrative denies the buffer fruit G6.0 sells as conventional")

    def test_no_event_record_claims_the_farm_has_no_conventional_product(self):
        problems = [
            f"{model} {row.get('date')}"
            for season in self.data["seasons"]
            for model, rows in season["events"].items()
            for row in rows
            for text in _strings(row)
            if self.BLANKET_CLAIM.search(text)
        ]
        self.assertEqual(problems, [])

    def test_the_annual_seedlings_answer_names_no_planting_stock_form(self):
        checked = 0
        problems = []
        for osp in self.data["osps"]:
            answers = osp["module_responses"]["modules"].get("g3_1_seedlings", {}).get("answers", {})
            for key, answer in answers.items():
                for text in _strings(answer.get("value") if isinstance(answer, dict) else answer):
                    checked += 1
                    for m in self.STOCK_TERMS.finditer(text):
                        problems.append(f"v{osp['version_number']} {key}: {m.group(0)!r}")
        self.assertGreater(checked, 0, "no annual-seedlings answer was read")
        self.assertEqual(problems, [], "a planting-stock form is described as an annual seedling")


class Run7SpecimenConsistencyTests(SimpleTestCase):
    """Run 7 (R7-12 and the fixture halves of R7-07b, R7-11, R7-13): the specimen tells one
    account. Checked against the fixture's own rows so a later edit that reintroduces a
    contradiction fails here. Missing external documents are not fabricated and are not checked
    for: they stay open on the specimen axis."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data = json.loads(FIXTURE.read_text())
        cls.by_id = {}

        def walk(obj):
            if isinstance(obj, dict):
                if "_id" in obj:
                    cls.by_id.setdefault(str(obj["_id"]), []).append(obj)
                for value in obj.values():
                    walk(value)
            elif isinstance(obj, list):
                for value in obj:
                    walk(value)

        walk(cls.data)

    def _one(self, _id):
        return self.by_id[str(_id)][0]

    def _season_events(self, model):
        return [e for s in self.data["seasons"] for e in s["events"].get(model, [])]

    def test_the_fresh_sale_names_every_pick_it_carried(self):
        sale = next(s for s in self.data["sales_records"] if str(s["_id"]) == "97")
        self.assertIn(4989, sale["~harvest_events"], "pick 1 (CBF-26-HFE-P1) is on no sale")
        self.assertNotIn("01..03", sale["bill_of_lading"])

    def test_a_load_is_sent_on_the_day_its_transport_record_says(self):
        events = self._season_events("ProductionEvent")
        transport = {e["harvest_lot_code"]: e for e in events if e.get("type") == "TP" and e.get("harvest_lot_code")}
        checked = 0
        for e in events:
            sent = e.get("sent_to_handler_date")
            if e.get("type") == "HA" and isinstance(sent, dict) and e.get("harvest_lot_code") in transport:
                checked += 1
                self.assertEqual(sent["__d__"], transport[e["harvest_lot_code"]]["date"]["__dt__"][:10], e["_id"])
        self.assertGreater(checked, 10)

    def test_every_stored_temperature_says_its_unit(self):
        keys = ("low_temperature", "highest_temperature", "lower_temperature", "lowest_temperature", "temperature")
        for model in EVENT_MODELS:
            for e in self._season_events(model):
                extra = e.get("extra_data")
                if isinstance(extra, dict) and any(k in extra for k in keys):
                    self.assertIn(extra.get("temperature_unit"), ("F", "C"), f"{model} {e['_id']}")

    def test_fish_through_the_drip_is_fertigation(self):
        for e in self._season_events("ChemicalEvent"):
            if e.get("way_of_application") == "chemigation" and "Neptune" in (e.get("commercial_name") or ""):
                self.assertIs(e.get("is_fertigation"), True, e["_id"])

    def test_the_feather_meal_narrative_names_the_corrected_lot(self):
        event = self._one(2786)
        self.assertEqual(event["chemical_lot_number"], "DTE-FM-2512-880")
        for key in ("description", "observation"):
            self.assertNotIn("DTE-FM-2512-088", event[key])

    def test_hive_removal_and_bloom_sprays_tell_one_account(self):
        placement = self._one(4986)
        removed = self._one(4893)["date"]["__dt__"][:10]
        self.assertEqual(placement["extra_data"]["removal_date"], removed)
        self.assertNotIn("16 May", placement["description"])
        active_plan = json.dumps(self.data["osps"][2])
        self.assertNotIn("Nothing is applied while hives are on the block.", active_plan)

    def test_entrust_goes_on_after_the_threshold_is_met(self):
        threshold = self._one(1730)["date"]["__dt__"][:10]
        entrust = sorted(
            e["date"]["__dt__"][:10]
            for e in self._season_events("ChemicalEvent")
            if (e.get("commercial_name") or "").startswith("Entrust SC") and str(e.get("#history")) == "692"
        )
        self.assertGreaterEqual(entrust[0], threshold)
        self.assertNotIn("ahead of colour", self._one(1730)["description"])

    def test_pick_one_culls_have_one_disposition(self):
        self.assertNotIn("WVF process", self._one(4990)["description"])
        self.assertIn("buried", self._one(1731)["description"])

    def test_the_certificate_event_states_the_parcels_acreage(self):
        self.assertNotIn("54.2 ac", self._one(434)["description"])
        self.assertIn("86.9 ac", self._one(434)["description"])

    def test_the_compost_records_show_the_five_turnings_the_plan_states(self):
        """Turns 4 and 5 are their own dated record (review of back #114: appending them to the
        25 August record forward-dated its log and flipped its own compliance verdict)."""
        pile = [
            e
            for e in self._season_events("SoilManagementEvent")
            if e.get("compost_unit_id") == "Windrow UT-2 (headland pad)"
        ]
        self.assertEqual(self._one(1327)["compost_turning_count"], 3)
        last = max(pile, key=lambda e: e["date"]["__dt__"])
        self.assertEqual(last["compost_turning_count"], 5)
        self.assertGreaterEqual(last["date"]["__dt__"][:10], "2026-09-08")

    def test_no_compost_log_is_dated_after_its_own_record(self):
        import re as _re

        for e in self._season_events("SoilManagementEvent"):
            log = e.get("compost_temperature_log") or ""
            for logged in _re.findall(r"^(\d{4}-\d{2}-\d{2})", log, flags=_re.M):
                self.assertLessEqual(logged, e["date"]["__dt__"][:10], f"{e['_id']} logs {logged}")

    def test_a_reading_the_narrative_gives_in_celsius_is_not_labelled_fahrenheit(self):
        """Review of back #114: the -2.2 frost reading is the narrative's Celsius figure."""
        keys = ("low_temperature", "highest_temperature", "lower_temperature", "lowest_temperature", "temperature")
        for model in EVENT_MODELS:
            for e in self._season_events(model):
                extra = e.get("extra_data")
                if not isinstance(extra, dict):
                    continue
                text = ((e.get("description") or "") + (e.get("observation") or "")).replace("\u2212", "-")
                for key in keys:
                    if key in extra and f"{str(extra[key]).lstrip('-')}°C" in text.replace("-", ""):
                        self.assertEqual(extra.get("temperature_unit"), "C", f"{model} {e['_id']} {key}")


class Run7bSpecimenResidualTests(SimpleTestCase):
    """Run 7b (Astra, 2026-10-04): the leftovers of the R7-12 reconciliation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data = json.loads(FIXTURE.read_text())

    def _season_events(self, model):
        return [e for s in self.data["seasons"] for e in s["events"].get(model, [])]

    def test_no_record_still_dates_the_first_entrust_on_19_june(self):
        for e in self._season_events("ChemicalEvent"):
            if str(e.get("#history")) == "692":
                self.assertNotIn("19 Jun", (e.get("description") or "") + (e.get("observation") or ""), e["_id"])

    def test_serenade_with_hives_in_goes_on_before_7am_never_at_dusk(self):
        for e in self._season_events("ChemicalEvent"):
            if str(e.get("#history")) == "692" and "Serenade" in (e.get("commercial_name") or ""):
                # Every field of the record, and its time (review of back #115: extra_data still
                # said dusk and the timestamp was 19:30). Fixture times are local.
                self.assertNotIn("dusk", json.dumps(e).lower(), e["_id"])
                self.assertLess(int(e["date"]["__dt__"][11:13]), 7, e["_id"])

    def test_an_application_that_skipped_the_buffer_is_not_recorded_as_the_entire_planting(self):
        for e in self._season_events("ChemicalEvent"):
            if "Buffer row skipped" in (e.get("description") or ""):
                self.assertEqual(e.get("applied_scope"), "part", e["_id"])
                self.assertTrue(e.get("applied_scope_detail"), e["_id"])


class Run8SpecimenPublicTextTests(SimpleTestCase):
    """Run 8 (R8-18): the demo published an invoice number from a spray note. The structured
    invoice field is where it belongs; no note repeats its own event's invoice."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data = json.loads(FIXTURE.read_text())

    def test_no_note_repeats_its_events_invoice_number(self):
        fields = ("purchase_invoice", "seed_purchase_invoice", "amendment_purchase_invoice")
        checked = 0
        for season in self.data["seasons"]:
            for events in season["events"].values():
                for e in events:
                    for f in fields:
                        ref = str(e.get(f) or "").strip()
                        if ref:
                            checked += 1
                            self.assertNotIn(ref, e.get("observation") or "", (e.get("_id"), f))
        self.assertGreater(checked, 0, "no invoice field found: the guard read nothing")


class CalapooiaGeographyAndSeasonTests(SimpleTestCase):
    """The page review of 2026-10-29 found Home Field East and Home Field West both claiming the
    Hartwell field on their west side, and spray, compost and fertilizer records dated days before
    the season they were counted in. A reviewer cross-checks both; so does this."""

    OPPOSITE = {"North": "South", "South": "North", "East": "West", "West": "East"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data = json.loads(FIXTURE.read_text())

    def test_neighboring_parcels_name_each_other_from_opposite_sides(self):
        parcels = {p["name"]: p for p in self.data["parcels"]}
        pairs = 0
        for name, parcel in parcels.items():
            for zone in parcel["buffer_zones"]:
                for other in parcels:
                    if other == name or other not in zone["adjoining_land_use"].replace(
                        "Home Field East / West", "Home Field East, Home Field West"
                    ):
                        continue
                    pairs += 1
                    back = [
                        z["direction"]
                        for z in parcels[other]["buffer_zones"]
                        if name
                        in z["adjoining_land_use"].replace("Home Field East / West", "Home Field East, Home Field West")
                    ]
                    self.assertIn(self.OPPOSITE[zone["direction"]], back, (name, zone["direction"], other, back))
        self.assertGreater(pairs, 0, "no parcel names a neighbor: the guard read nothing")

    def test_no_record_is_dated_before_its_season_starts(self):
        checked = 0
        for season in self.data["seasons"]:
            start = season["start_date"]["__dt__"][:10]
            for model, events in season["events"].items():
                for e in events:
                    when = (e.get("date") or {}).get("__dt__", "")[:10]
                    if when:
                        checked += 1
                        self.assertGreaterEqual(when, start, (season["name"], model, e.get("_id")))
        self.assertGreater(checked, 0)
