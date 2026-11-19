"""The Calapooia fixture must still describe the models it is loaded into.

WHY THIS EXISTS
---------------
`seed_calapooia_bend` rebuilds the deepest dataset Trazo has — 6 parcels, 12 seasons, 510
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
It does not run the seeder. That writes 510 events and fires the carbon signals on every one,
and a test that slow gets skipped, which is worse than not having it. Fidelity of the OUTPUT is
verified by rebuilding into a clean database and diffing the certifier packet against the
source — DOCUMENTED 15 = 15, GAP 2 = 2, with the single remaining difference being the
rehearsal's own audit trail, which must not be reproduced.
"""

import io
import json
import re
from pathlib import Path

from django.apps import apps
from django.test import SimpleTestCase, TestCase

# The loader's own type-marker decoder. Imported rather than reimplemented: a guard that
# decodes differently from the seeder is testing a document nobody loads.
from history.management.commands.seed_calapooia_bend import _decode

FIXTURE = Path(apps.get_app_config("history").path) / "management" / "commands" / "_calapooia_bend_data.json"

#: Fixture section -> the model its rows are loaded into.
SECTION_MODEL = {
    "establishment": ("company", "Establishment"),
    "parcels": ("product", "Parcel"),
    "seasons": ("history", "Production"),
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
        # 510 since 2026-11-18: the two Real Organic Project inspection records are dropped with the
        # certificate (VID-15; `test_no_certificate_is_issued_by_a_real_programme_...`).
        self.assertEqual(events, 510, "the fixture no longer holds the farm it was extracted from")
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
        self.assertEqual(checked, 510, "not every event row was checked")
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

    def _applications(self):
        for season in self.data["seasons"]:
            for model in ("ChemicalEvent", "SoilManagementEvent"):
                yield from season["events"].get(model, [])

    def _plan_basis(self):
        """Product name -> the listing basis the plan files it under, and the OMRI row it names."""
        return {
            e["product_name"]: (e.get("listing_basis"), (e.get("@omri_product") or None))
            for e in self.data["plan_material_entries"]
        }

    def test_an_application_carries_the_omri_listing_its_plan_names(self):
        """VID-11 (recordkeeping checklist run 2026-11-16): the dossier's plan pages cited the
        OMRI number of Neptune's Harvest and five other products, while every application row said
        "OMRI Listed, grower-selected, no listing on file". The row was right about the record: the
        seeded applications never carried the listing a grower attaches when logging one. They do
        now, the row the plan names, matched by the fixture's exact product name."""
        plan = self._plan_basis()
        omri = set(self.data["approved_input_rows"]["OMRIProduct"])
        checked = 0
        for row in self._applications():
            name = row.get("commercial_name")
            if name in omri and row.get("organic_approved") == "omri_listed":
                checked += 1
                self.assertEqual((row.get("@omri_product") or {}).get("product_name"), name, name)
                self.assertEqual(plan[name][0], "omri", name)
        self.assertGreater(checked, 50, "no OMRI application read")
        # And the other way: a link sits only on an OMRI application of the product it names.
        for row in self._applications():
            link = (row.get("@omri_product") or {}).get("product_name")
            if link:
                self.assertEqual(row.get("commercial_name"), link, link)
                self.assertEqual(row.get("organic_approved"), "omri_listed", link)

    def test_no_application_claims_a_listing_its_plan_says_it_does_not_have(self):
        """Rex Lime Sulfur, Rexius compost and Tiger 90CR sulfur sit on the plan as a National List
        substance or an unlisted material, and their applications said "OMRI Listed" with no
        listing anywhere. On the record they are now what the approved plan makes them: reviewed
        and approved by the certifier."""
        plan = self._plan_basis()
        read = 0
        for row in self._applications():
            name = row.get("commercial_name") or row.get("amendment_product_name") or ""
            basis = row.get("organic_approved") or row.get("amendment_organic_approved")
            entry = next((v for k, v in plan.items() if name and (name == k or name.startswith(k))), None)
            if entry is None or not basis:
                continue
            read += 1
            if entry[0] in ("national_list", "none_unlisted"):
                self.assertNotEqual(basis, "omri_listed", name)
        self.assertGreater(read, 50, "no planned application read")

    def test_no_free_text_calls_an_unlisted_material_omri(self):
        """Rexius compost is "no third-party listing" on the plan; its records and the farm's
        profile said "Rexius OMRI compost" (review of back #496), the same contradiction inside one
        record."""
        text = json.dumps(self.data)
        self.assertNotIn("OMRI compost", text)

    def test_an_npk_product_name_and_its_percentages_agree(self):
        """Neptune's Harvest 2-4-1 printed 2-3-1, and one row kept P at 3% after the fix."""
        for row in self._applications():
            if row.get("commercial_name") != "Neptune's Harvest Organic Fish Fertilizer 2-4-1":
                continue
            p = row.get("phosphorus_percentage")
            if p is not None:
                self.assertEqual(p, {"__dec__": "4.00"}, row.get("_id"))

    def test_the_specimen_records_agree_with_each_other(self):
        """VID-15 (recordkeeping checklist run 2026-11-16): the specimen printed facts its own records
        contradicted. Upper Terrace onions "11.8 ac" on a 14.2 ac parcel whose every soil record and
        harvest arithmetic use 14.2; a season note "89,300 lb packed out" over pick records that sum
        to 89,562; "BOL BOL CBF-..." (the value carried the label); "Pressure 6.00/trap" on 58 trap
        rows, which was the trap count, while the catch sat in the trap detail; and a threshold the
        rationale said "first male catch" while the strategy and the plan said "the first confirmed
        SWD female".
        """
        text = json.dumps(self.data, ensure_ascii=False)
        for stale in ("11.8 ac", "89,300 lb packed out", "first male catch"):
            self.assertNotIn(stale, text, stale)
        # The plan's threshold is the records' threshold (review of back #499: rewording the 98
        # strategy rows split them from the plan's G5 answers, which say "first confirmed female").
        self.assertNotIn("SWD trap catch", text)
        # A record that says 14.2 ac also stores 14.2 ac.
        for season in self.data["seasons"]:
            for rows in season["events"].values():
                for r in rows:
                    if "14.2 ac" in json.dumps(r, ensure_ascii=False) and r.get("area_covered") is not None:
                        area = r["area_covered"]
                        self.assertEqual(area.get("__dec__") if isinstance(area, dict) else area, "14.20", r["_id"])
        sales_bols = [
            r.get("bill_of_lading") or ""
            for s in self.data["seasons"]
            for model in ("ProductionEvent",)
            for r in s["events"].get(model, [])
        ] + [r.get("bill_of_lading") or "" for r in self.data["sales_records"]]
        self.assertTrue(any(sales_bols), "no bill of lading read")
        self.assertFalse([b for b in sales_bols if b.startswith("BOL ")])
        pests = [r for s in self.data["seasons"] for r in s["events"].get("PestManagementEvent", [])]
        self.assertGreater(len([r for r in pests if r.get("type") == "TM"]), 50, "no trap row read")
        # Any pest row, not only TM: four carrot rows with no subtype carried the same "6/trap".
        self.assertFalse(
            [
                r["_id"]
                for r in pests
                if r.get("monitoring_unit") == "per_trap" and (r.get("monitoring_count") or {}).get("__dec__") == "6.00"
            ],
            "a pest row stores the trap count as its pressure",
        )

    def test_every_national_list_link_says_how_it_was_set(self):
        """A National List link with no basis prints "recorded before Trazo kept how it was matched;
        not verified": a false history for records written in 2026 (the seeder writes rows directly,
        never through the form that records the basis)."""
        linked = [r for r in self._applications() if "@national_list_substance" in r]
        self.assertTrue(linked, "no National List link read")
        for row in linked:
            self.assertEqual(row.get("national_list_basis"), "operator", row.get("commercial_name"))

    def test_no_certificate_is_issued_by_a_real_programme_the_substitution_cannot_rename(self):
        """Recordkeeping checklist run 2026-11-16, VID-15: the substitution renamed the Real Organic
        Project's certifier to "Living Soil Standard", but the row kept
        `certification_type="real_organic_project"`, which every surface displays as "Real Organic
        Project", a certificate number in its "ROP-" form, and an add-on inspection by a named
        inspector. A type and a number are not names, so no string substitution reaches them.
        Oscar's call (2026-11-18): drop it. The specimen holds one certificate, USDA Organic, from
        the invented certifier the substitution produces.
        """
        self.assertEqual({c["certification_type"] for c in self.data["certifications"]}, {"usda_organic"})
        business = [e for s in self.data["seasons"] for e in s["events"].get("BusinessEvent", [])]
        self.assertTrue(business, "no business record read")
        self.assertEqual({e.get("certification_type") for e in business} - {"", None, "organic_usda"}, set())
        text = json.dumps(self.data)
        for real in ("Real Organic", "ROP-"):
            self.assertNotIn(real, text, f"{real!r} is back in the specimen")
        # The bare acronym too, on word boundaries ("CROPS" is not it): a season narrative kept
        # "ROP inspection on the block" after its record was dropped (review of back #488).
        self.assertIsNone(re.search(r"\bROP\b", text), "the ROP acronym is back in the specimen")


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


class SeederOwnerTests(TestCase):
    """VID-15: `--owner-email` took a consumer account, which then owned the farm and could not
    sign in to the app subdomain to see it."""

    def test_a_consumer_account_is_refused_before_anything_is_written(self):
        from django.core.management import CommandError, call_command

        from company.models import Establishment
        from users.constants import CONSUMER
        from users.models import User

        User.objects.create_user(email="shopper@test.com", password="unused-Pw-2026", user_type=CONSUMER)
        with self.assertRaisesMessage(CommandError, "not a producer account"):
            call_command("seed_calapooia_bend", owner_email="shopper@test.com", stdout=io.StringIO())
        self.assertFalse(Establishment.objects.exists())


class SpecimenPlanAgreesWithItsRecordsTests(SimpleTestCase):
    """Three places where the specimen's plan and its records told different stories (recordkeeping
    checklist run 2026-11-16): an inspector reads both, and a demo that disagrees with itself
    teaches the wrong habit."""

    MONTHS = r"January|February|March|April|May|June|July|August|September|October|November|December"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.raw = FIXTURE.read_text()
        cls.data = json.loads(cls.raw)

    def _season_events(self, model):
        return [e for s in self.data["seasons"] for e in s["events"].get(model, [])]

    def _answers(self, key):
        found = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == key:
                        found.append(v.get("value") if isinstance(v, dict) else v)
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(self.data)
        return found

    def test_the_five_windrow_turnings_fall_inside_fifteen_days(self):
        """§ 205.203(c)(2)(ii): 131-170 °F for 15 days, "during which period" five turnings. The
        records spread them over 30 days (9 August to 8 September), which no 15-day window holds."""
        from datetime import date

        turns = {}
        for e in self._season_events("SoilManagementEvent"):
            if e.get("compost_unit_id") != "Windrow UT-2 (headland pad)":
                continue
            for day, n in re.findall(r"^(\d{4}-\d{2}-\d{2}) turn (\d)", e.get("compost_temperature_log") or "", re.M):
                turns[int(n)] = date.fromisoformat(day)
        self.assertEqual(sorted(turns), [1, 2, 3, 4, 5])
        self.assertLessEqual((max(turns.values()) - min(turns.values())).days, 14, turns)

    def test_the_plan_states_the_turning_practice_not_dates_it_had_not_reached(self):
        """The answer is dated 21 August and named turnings on 25 August to 8 September."""
        answers = [a for a in self._answers("compost_turnings") if a]
        self.assertTrue(answers)
        for answer in answers:
            self.assertNotRegex(answer, self.MONTHS)
        for line in re.findall(r"Number of windrow turnings: [^\\]*", self.raw):
            self.assertNotRegex(line, self.MONTHS)

    def test_acres_to_certify_is_each_parcels_area(self):
        """The filed revisions certify 86.9 acres across six parcels, buffer rows included; the
        per-parcel answers added up to 84.5."""
        total = 0.0
        for parcel in self.data["parcels"]:
            area_acres = round(float(parcel["area"]) * 2.47105, 1)
            answer = self._parcel_answer(parcel, "acres_to_certify")
            self.assertEqual(float(answer), area_acres, parcel["name"])
            total += float(answer)
        self.assertAlmostEqual(total, 86.9, places=6)

    def _parcel_answer(self, parcel, key):
        found = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == key:
                        found.append(v.get("value") if isinstance(v, dict) else v)
                    else:
                        walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(parcel)
        self.assertEqual(len(found), 1, parcel["name"])
        return found[0]

    def test_the_plan_names_the_deepest_tillage_the_records_show(self):
        """The plan said the 6-inch rototill was "the deepest we go"; four records chisel to 8-10 in."""
        self.assertNotIn("the deepest we go", self.raw)
        depths = [
            float(_decode(e["working_depth"]))
            for e in self._season_events("SoilManagementEvent")
            if e.get("type") == "TI" and e.get("working_depth")
        ]
        self.assertEqual(max(depths), 10.0)
        self.assertIn("spring chisel pass to eight to ten inches", self.raw)

    def test_no_autumn_tillage_where_the_parcels_say_spring_only(self):
        """Bottom Ground A and B: "spring chisel only, no fall tillage"; the plan disced residue in
        every autumn."""
        self.assertNotIn("flail-mowed and disced in and the cover is drilled", self.raw)
        for e in self._season_events("SoilManagementEvent"):
            if e.get("type") == "TI":
                self.assertNotIn(e["date"]["__dt__"][5:7], ("09", "10", "11", "12"), e["_id"])
