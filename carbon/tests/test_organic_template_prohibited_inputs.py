"""
An organic production template must never carry a 7 CFR 205.105 prohibited substance.

This is not hypothetical. Until 2026-08-03 the ONLY template shipped for walnuts, almonds,
grapes, blueberries and hops was the conventional one, whose input list includes
"Roundup PowerMax 3 (glyphosate)". An organic grower opening the "Smart Setup" flow was
offered exactly one template and it was a prohibited-input one — and because template events
pre-fill a real event attributed to that farmer by name, accepting it would have written a
glyphosate application into their own audit trail.

The organic overrides are plain data, and the organic event generators are pure functions, so
this asserts against them directly rather than against a seeded database: a crop added to
ORGANIC_OVERRIDES with a synthetic input fails here, before anything is seeded anywhere.
"""

import json
import re

from django.test import SimpleTestCase

from carbon.management.commands.create_comprehensive_production_templates_v2 import (
    CROP_CUSTOMIZATIONS,
    ORGANIC_OVERRIDES,
    get_annual_crop_organic_events,
    get_tree_crop_organic_events,
)

# Substances prohibited under 7 CFR 205.105, plus the specific conventional trade names the
# conventional templates in this same module reach for. Matching on trade names as well as
# active ingredients catches a copy-paste from the conventional block, which is how every
# instance of this bug has actually happened.
PROHIBITED_SUBSTRINGS = [
    "glyphosate",
    "roundup",
    "ammonium sulfate",
    "urea",
    "osmocote",
    "yaramila",
    "mefenoxam",
    "ridomil",
    "quinoxyfen",
    "quintec",
    "spirotetramat",
    "movento",
    "spinetoram",
    "delegate",
    "cyprodinil",
    "fludioxonil",
    "switch 62",
]


def _names_prohibited_substance(blob):
    """Return the prohibited terms present in `blob`, matched on word boundaries.

    Plain substring matching is a trap here: "urea" is a substring of "b-UREA-u", so a
    perfectly legitimate certifier like "Bureau Veritas Certification" in `certification_body`
    would have failed these tests as a prohibited synthetic fertilizer. Word boundaries keep
    "Urea 46-0-0" caught and "Bureau" clean.
    """
    return [term for term in PROHIBITED_SUBSTRINGS if re.search(rf"\b{re.escape(term)}\b", blob)]


# Subtypes that are conventional-by-definition. `organic_approved` is a separate field; a
# subtype of synthetic_* is a contradiction no organic template may contain.
PROHIBITED_SUBTYPES = [
    "synthetic_fertilizer",
    "synthetic_pesticide",
    "synthetic_fungicide",
    "synthetic_herbicide",
]

# Mirrors CHEMICAL_SUBTYPES_BY_MAIN_TYPE in trazo-app/src/config/events/enums.ts.
# A template that writes a subtype absent from the form renders its raw enum key to the
# farmer — the same class of defect as `air_blast` on the consumer card, where the value was
# added to one map and not the other. Keep this list in sync with enums.ts.
FORM_KNOWN_SUBTYPES = {
    "synthetic_fertilizer",
    "organic_fertilizer",
    "slow_release_fertilizer",
    "synthetic_pesticide",
    "organic_pesticide",
    "biological_pesticide",
    "synthetic_fungicide",
    "organic_fungicide",
    "copper_fungicide",
    "sulfur_fungicide",
    "biological_fungicide",
    "synthetic_herbicide",
    "organic_herbicide",
}


def _generated_events(crop_slug):
    """Every event both organic generators would produce for this crop.

    Routing is by CropType.category, which lives in the database. Generating from both paths
    keeps this a pure data test while still covering whichever one the crop actually takes.
    """
    crop_data = CROP_CUSTOMIZATIONS[crop_slug]
    overrides = ORGANIC_OVERRIDES[crop_slug]
    return get_tree_crop_organic_events(crop_slug, crop_data, overrides) + get_annual_crop_organic_events(
        crop_slug, crop_data, overrides
    )


class OrganicOverrideDataTests(SimpleTestCase):
    def test_every_organic_override_names_a_crop_that_exists(self):
        for crop_slug in ORGANIC_OVERRIDES:
            self.assertIn(
                crop_slug,
                CROP_CUSTOMIZATIONS,
                f"{crop_slug} has organic overrides but no crop data — the seeder would KeyError",
            )

    def test_no_override_carries_a_synthetic_herbicide(self):
        # Mechanical cultivation and mowing replace herbicides in organic systems. The field
        # must be explicitly None, not merely absent, so the generator emits no spray event.
        for crop_slug, overrides in ORGANIC_OVERRIDES.items():
            self.assertIsNone(
                overrides.get("herbicide"),
                f"{crop_slug} organic override carries herbicide={overrides.get('herbicide')!r}",
            )

    def test_no_override_declares_a_synthetic_subtype(self):
        for crop_slug, overrides in ORGANIC_OVERRIDES.items():
            for key, value in overrides.items():
                if not isinstance(value, str):
                    continue
                self.assertNotIn(
                    value,
                    PROHIBITED_SUBTYPES,
                    f"{crop_slug}.{key} = {value!r} is conventional-by-definition",
                )

    def test_no_override_names_a_prohibited_substance(self):
        for crop_slug, overrides in ORGANIC_OVERRIDES.items():
            hits = _names_prohibited_substance(json.dumps(overrides).lower())
            self.assertEqual(
                hits,
                [],
                f"{crop_slug} organic override names {hits} (7 CFR 205.105 prohibited)",
            )

    def test_the_prohibited_matcher_is_not_fooled_by_substrings(self):
        # Guards the matcher itself. "Bureau Veritas" is a real certification body and would
        # be a false positive under naive substring matching on "urea".
        self.assertEqual(_names_prohibited_substance("bureau veritas certification"), [])
        self.assertEqual(_names_prohibited_substance("urea 46-0-0"), ["urea"])
        self.assertEqual(_names_prohibited_substance("roundup powermax 3 (glyphosate)"), ["glyphosate", "roundup"])


class OrganicGeneratedEventTests(SimpleTestCase):
    def test_the_generators_actually_produce_events(self):
        # Guards every other test in this class. All of them iterate generated events and pass
        # trivially if that iteration is empty, so an exception-swallowing or renamed generator
        # would turn this whole file green while checking nothing.
        for crop_slug in ORGANIC_OVERRIDES:
            self.assertGreater(len(_generated_events(crop_slug)), 10, f"{crop_slug} generated almost no events")

    def test_chemical_events_are_actually_present_to_inspect(self):
        # Same vacuity guard, one level down: the subtype and prohibited-substance checks only
        # mean something if the generated events include chemical applications.
        for crop_slug in ORGANIC_OVERRIDES:
            subtypes = [
                (e.get("backend_event_fields") or {}).get("chemical_subtype") for e in _generated_events(crop_slug)
            ]
            self.assertGreater(
                len([s for s in subtypes if s]),
                0,
                f"{crop_slug} generated no chemical events — the subtype checks would be vacuous",
            )

    def test_copper_spray_targets_a_disease_of_that_crop(self):
        # The copper target was hardcoded to avocado anthracnose for EVERY tree crop, so the
        # organic walnut, grape, stone fruit, hazelnut and pecan copper sprays each recorded a
        # disease that does not occur on them. `copper_target` existed in the data; nothing
        # read it. Assert the value reaches the event rather than trusting the wiring.
        for crop_slug, overrides in ORGANIC_OVERRIDES.items():
            expected = overrides.get("copper_target")
            if not expected:
                continue
            copper_targets = [
                (e.get("backend_event_fields") or {}).get("target_pest_disease")
                for e in _generated_events(crop_slug)
                if (e.get("backend_event_fields") or {}).get("chemical_subtype") == "copper_fungicide"
            ]
            self.assertTrue(copper_targets, f"{crop_slug} generated no copper event")
            for actual in copper_targets:
                self.assertEqual(
                    actual,
                    expected,
                    f"{crop_slug} copper spray records {actual!r}, not its own {expected!r}",
                )

    def test_every_organic_crop_with_copper_declares_what_it_treats(self):
        for crop_slug, overrides in ORGANIC_OVERRIDES.items():
            if not overrides.get("copper_fungicide"):
                continue
            self.assertTrue(
                overrides.get("copper_target"),
                f"{crop_slug} sprays copper with no copper_target — it would fall back to a "
                "generic disease string on the certifier record",
            )

    def test_generated_events_contain_no_prohibited_substance(self):
        for crop_slug in ORGANIC_OVERRIDES:
            for event in _generated_events(crop_slug):
                blob = json.dumps(
                    {
                        "name": event.get("name"),
                        "description": event.get("description"),
                        "fields": event.get("backend_event_fields", {}),
                    }
                ).lower()
                hits = _names_prohibited_substance(blob) + [s for s in PROHIBITED_SUBTYPES if s in blob]
                self.assertEqual(
                    hits,
                    [],
                    f"{crop_slug} organic event {event.get('name')!r} contains {hits}",
                )

    def test_no_organic_template_generates_a_herbicide_event(self):
        # `herbicide: None` in the overrides is asserted elsewhere, but NOTHING READS that key —
        # the generators simply never emit a herbicide event. That makes the data assertion
        # documentation rather than a guarantee, so assert the generated output directly.
        for crop_slug in ORGANIC_OVERRIDES:
            for event in _generated_events(crop_slug):
                subtype = (event.get("backend_event_fields") or {}).get("chemical_subtype") or ""
                self.assertNotIn(
                    "herbicide",
                    subtype,
                    f"{crop_slug} organic template emits a herbicide event ({event.get('name')!r})",
                )

    def test_generated_chemical_subtypes_are_all_selectable_in_the_form(self):
        for crop_slug in ORGANIC_OVERRIDES:
            for event in _generated_events(crop_slug):
                fields = event.get("backend_event_fields") or {}
                for key in ("chemical_subtype", "type"):
                    value = fields.get(key)
                    if not isinstance(value, str):
                        continue
                    # Only chemical subtypes are constrained here; `type` also carries
                    # non-chemical activity codes for other event models.
                    if not any(tok in value for tok in ("fertilizer", "pesticide", "fungicide", "herbicide")):
                        continue
                    self.assertIn(
                        value,
                        FORM_KNOWN_SUBTYPES,
                        f"{crop_slug} writes {key}={value!r}, absent from enums.ts — "
                        "it would render as a raw enum key",
                    )

    def test_every_perennial_crop_has_organic_coverage(self):
        # The GTM ICP is perennial specialty crops — orchards, vineyards and PNW berries/hops.
        # A perennial without an organic override means growers in that segment open Smart
        # Setup and are offered exactly one template, the conventional one.
        #
        # Category lives on CropType in the database, so the perennials are named here rather
        # than derived. Row crops and annual vegetables are deliberately NOT in this list:
        # they are outside the ICP and still conventional-only, which is a known gap, not a
        # regression this test should fail on.
        perennials = (
            # tree_nut
            "walnuts",
            "almonds",
            "pecans",
            "hazelnuts",
            # tree_fruit
            "apples",
            "avocados",
            "citrus_oranges",
            "grapes",
            "stone_fruit",
            # berry / vine
            "blueberries",
            "hops",
        )
        for crop_slug in perennials:
            self.assertIn(
                crop_slug,
                ORGANIC_OVERRIDES,
                f"{crop_slug} has no organic template — organic growers get a glyphosate template",
            )


class OrganicVegetableTemplateTests(SimpleTestCase):
    """F4 (Calapooia Bend, 2026-08-21) — the four organic vegetable templates.

    Carrots, onions, spinach and potatoes shipped with a CONVENTIONAL template and nothing
    else, so an organic vegetable grower starting a season was offered exactly one plan — one
    whose items include Herbicide Application, Pesticide Treatment, Fungicide Treatment and a
    GLOBALG.A.P. audit. A template writes a season PLAN and never a record, so nothing false
    was logged; the cost is that the checklist an organic grower works from starts wrong and
    every practice their season actually turns on is absent.
    """

    VEGETABLES = ("carrots", "onions", "spinach", "potatoes")

    def test_each_organic_vegetable_has_an_override_at_all(self):
        # The seeder creates an organic template ONLY when ORGANIC_OVERRIDES has an entry, so
        # this membership check is the whole feature. All four had a CROP_CUSTOMIZATIONS entry
        # (hence a conventional template) and no organic one, which is exactly why the gap was
        # invisible until a grower opened the picker.
        for crop_slug in self.VEGETABLES:
            self.assertIn(crop_slug, CROP_CUSTOMIZATIONS, f"{crop_slug} lost its practice data")
            self.assertIn(crop_slug, ORGANIC_OVERRIDES, f"{crop_slug} has no organic template")

    def test_no_organic_vegetable_template_carries_a_herbicide(self):
        """The single most visible defect: "Herbicide Application" on an organic plan."""
        for crop_slug in self.VEGETABLES:
            self.assertIsNone(
                ORGANIC_OVERRIDES[crop_slug].get("herbicide"),
                f"{crop_slug} organic override names a herbicide",
            )
            for event in _generated_events(crop_slug):
                fields = event.get("backend_event_fields") or {}
                self.assertNotEqual(
                    fields.get("chemical_subtype"),
                    "synthetic_herbicide",
                    f"{crop_slug} organic template emits a synthetic herbicide event",
                )

    def test_the_season_a_vegetable_grower_actually_runs_is_on_the_plan(self):
        """The other half of F4: what the conventional template offered was wrong, and what an
        organic season is MADE of was missing. § 205.204(a)(1) seed search, purchased compost
        and pre-emergence flame weeding are the three the rehearsal named by name."""
        for crop_slug in self.VEGETABLES:
            subtypes = {(e.get("backend_event_fields") or {}).get("type") for e in _generated_events(crop_slug)}
            self.assertIn("SS", subtypes, f"{crop_slug}: no organic-seed search on the plan")
            self.assertIn("OM", subtypes, f"{crop_slug}: no compost application on the plan")
            self.assertIn("CU", subtypes, f"{crop_slug}: no cultivation/weed control on the plan")
            names = [e["name"] for e in _generated_events(crop_slug)]
            self.assertIn("Pre-Emergence Flame Weeding", names, f"{crop_slug}: no flame weeding")

    def test_the_seed_search_is_on_every_annual_organic_plan_not_just_the_new_ones(self):
        """§ 205.204(a) binds every organic crop grown from seed or planting stock, so the
        search is not a vegetable extra — the existing lettuce/tomato/strawberry templates
        were missing a record the certifier asks for by name."""
        for crop_slug in ("lettuce", "tomatoes", "strawberries"):
            names = [e["name"] for e in _generated_events(crop_slug)]
            self.assertIn(
                "Organic Seed Sourcing & Availability Search",
                names,
                f"{crop_slug} organic template has no seed-search item",
            )

    def test_onions_are_cured_not_washed(self):
        """A gated event must actually be gated. Storage onions are field- and shed-cured,
        topped and sacked — never washed — so a wash-and-sanitize item on their plan would put
        a food-safety record on the checklist that the crop's own handling contradicts. It is
        the reverse test of the three above: proof the gate can say NO."""
        self.assertNotIn("wash_water_sanitizer", ORGANIC_OVERRIDES["onions"])
        onion_names = [e["name"] for e in _generated_events("onions")]
        self.assertNotIn("Post-Harvest Wash & Sanitize", onion_names)
        # …while a washed crop does get it.
        self.assertIn("Post-Harvest Wash & Sanitize", [e["name"] for e in _generated_events("carrots")])

    def test_potatoes_name_the_bt_that_works_on_a_beetle(self):
        """kurstaki is a caterpillar material and does nothing to a Colorado potato beetle.
        Naming the wrong Bt is the kind of detail a grower notices and a certifier does not,
        which makes it worse than naming none."""
        biological = ORGANIC_OVERRIDES["potatoes"]["biological_pesticide"].lower()
        self.assertIn("tenebrionis", biological)
        self.assertNotIn("kurstaki", biological)

    def test_every_spray_names_its_ACTIVE_not_only_a_brand(self):
        """7 CFR 205.601 lists SUBSTANCES; a brand never appears there and never will.

        ⚠️ MEASURED, after getting it wrong. I first wrote this test asserting that spelling
        the organism out makes the string classifiable, and it does not: `history/signals.py`
        classifies a logged input by `extra_data.active_ingredient` FIRST and `commercial_name`
        second, and a product string ("DiPel DF (Bacillus thuringiensis subsp. kurstaki) — OMRI
        Listed") matches nothing at either step, because the National List's reverse pass needs
        the operator's text to be a SUBSTRING of the listing. The path that works is the
        farmer's own active-ingredient field, and a template cannot fill it — a template writes
        a season PLAN, and a plan item carries no field values.

        So what this test can honestly assert is narrower, and still worth having: the suggested
        product NAMES the substance a certifier would look up, rather than only a trade name.
        That is what the grower copies into the active-ingredient box, and it is the difference
        between a citation and "Self-reported" on the packet."""
        # Each of these is a name the classifier places when the grower enters it as the
        # ACTIVE INGREDIENT — verified against `history/signals.py` end to end, not assumed.
        # "insecticidal soap" rather than "potassium salts of fatty acids": the chemical name
        # is the active in soap-based HERBICIDES too, so it is in
        # `AMBIGUOUS_NEVER_AUTO_RESOLVE` and deliberately does not resolve.
        RESOLVABLE_ACTIVES = (
            "spinosad",
            "bacillus",
            "copper hydroxide",
            "insecticidal soap",
            "peracetic acid",
            "elemental sulfur",
            "horticultural oil",
        )
        for crop_slug in self.VEGETABLES:
            overrides = ORGANIC_OVERRIDES[crop_slug]
            for key in ("primary_fungicide", "copper_fungicide", "primary_pesticide", "biological_pesticide"):
                value = (overrides.get(key) or "").lower()
                if not value:
                    continue
                self.assertTrue(
                    any(active in value for active in RESOLVABLE_ACTIVES),
                    f"{crop_slug}.{key} = {overrides[key]!r} names no National-List active",
                )
