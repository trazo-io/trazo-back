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
    "osps": ("certifications", "OrganicSystemPlan"),
    "annual_updates": ("certifications", "OSPAnnualUpdate"),
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
