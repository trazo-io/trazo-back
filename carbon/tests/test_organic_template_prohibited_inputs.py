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
