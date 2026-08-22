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
