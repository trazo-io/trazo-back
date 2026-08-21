"""F5 — ONE harvest-grade vocabulary, crop-aware, carrying the USDA grade families.

## What went wrong

Two vocabularies for one fact, and neither was a grade anyone uses:

  * `ProductionEvent.harvest_quality_grade` — Export Quality / Grade A / Grade B / Grade C /
    Domestic Market / Processing.
  * `History.quality_grade`, the SEASON HEADER — a DIFFERENT list: Premium / Grade A /
    Grade B / Standard / Processing.

So a lot header and the harvest picks underneath it could not agree with each other, and the
certifier packet printed both. A previous rehearsal's reviewer found "Premium Grade" on a
header beside "WA Extra Fancy" on the picks and said the obvious thing: *"Grade A is not an
apple grade."* Real packing records read "U.S. No. 1", "U.S. Commercial", "WA Extra Fancy" —
none of which was offered, so the farmer picked the least-wrong option and the packet printed
a grade the certifier could not match to the packing record.

## What is pinned here

  1. Both columns draw on the SAME catalogue. That is the whole finding.
  2. The catalogue is crop-aware: an apple grower is never offered an onion grade.
  3. A crop with no USDA standard gets NO suggestions — inventing "U.S. No. 1" for a commodity
     with no such standard is the same defect one level up.
  4. Every active crop is mapped, so adding one forces a decision instead of silently
     inheriting a wrong family.
  5. The Python catalogue and its TypeScript mirror are identical. Two copies of a controlled
     vocabulary is how the original defect happened; a drift here recreates it.
  6. The stored value is the printed value — the packet reproduces a real grade verbatim, and
     still renders a legacy slug as its label.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from history.harvest_grades import (
    CROP_GRADE_FAMILY,
    GRADE_FAMILIES,
    LEGACY_GRADE_LABELS,
    MAX_GRADE_LENGTH,
    OTHER_GRADE,
    OTHER_GRADE_LABEL,
    all_grades,
    grades_for_crop,
)
from history.models import History, ProductionEvent
from history.services.audit_export_service import _humanize_enum

# `settings.BASE_DIR` is trazo-back/backend, so the repo root is TWO levels up.
TS_CATALOGUE = Path(settings.BASE_DIR).resolve().parent.parent / "trazo-app" / "src" / "config" / "harvestGrades.ts"


class OneVocabularyTests(SimpleTestCase):
    def test_the_two_columns_are_the_same_shape(self):
        """The finding was that the header and its own picks offered DIFFERENT lists. They now
        carry no list at all — the one catalogue is what both forms render — so what is left to
        assert here is that neither column has quietly grown a vocabulary of its own again."""
        for model, field in ((ProductionEvent, "harvest_quality_grade"), (History, "quality_grade")):
            column = model._meta.get_field(field)
            self.assertEqual(column.max_length, MAX_GRADE_LENGTH)
            self.assertFalse(
                column.choices,
                f"{model.__name__}.{field} declares choices again — that makes DRF generate a "
                "ChoiceField and the free-text escape starts answering 400.",
            )
            self.assertIn("harvest_grades", column.help_text)

    def test_neither_column_enforces_a_vocabulary(self):
        """⚠️ THE TEST THAT WAS MISSING. This shipped once with `choices=` on both columns.

        The picker rendered "Other — as stated on the packing record", the farmer typed their
        packer's house grade, and the API answered **400 "…is not a valid choice"** — a render
        gate with no payload path, which is the exact shape this rehearsal keeps finding. The
        UI check passed because I never SAVED through the escape.

        Asserted through the serializers, not the model: `Model.save()` never enforced choices,
        so a model-level test would have passed while the API refused.
        """
        from history.serializers import HistoryWriteSerializer, ProductionEventSerializer

        for serializer_class, field in (
            (HistoryWriteSerializer, "quality_grade"),
            (ProductionEventSerializer, "harvest_quality_grade"),
        ):
            declared = serializer_class().fields[field]
            self.assertFalse(
                hasattr(declared, "choices"),
                f"{serializer_class.__name__}.{field} is a {type(declared).__name__} — a grade "
                "the packing record actually states would be refused.",
            )
            self.assertEqual(declared.max_length, MAX_GRADE_LENGTH)

    def test_the_columns_are_wide_enough_for_the_catalogue_and_for_free_text(self):
        """A grade that does not fit is a 400 on save. The longest catalogue entry is
        "U.S. Standard Sheller Run"; the free-text escape needs headroom past that."""
        longest = max(len(grade) for grade in all_grades())
        self.assertLessEqual(longest, MAX_GRADE_LENGTH)
        self.assertGreater(MAX_GRADE_LENGTH - longest, 20, "no headroom left for a typed grade")


class CropAwarenessTests(SimpleTestCase):
    def test_an_apple_grower_is_never_offered_an_onion_grade(self):
        """The reason this is crop-aware and not one flat list."""
        apple = grades_for_crop("apples")
        onion = grades_for_crop("onions")
        self.assertIn("WA Extra Fancy", apple)
        self.assertNotIn("WA Extra Fancy", onion)
        self.assertIn("U.S. Commercial", onion)
        self.assertNotIn("U.S. Commercial", apple)

    def test_the_pilot_farms_own_crops_get_the_grades_its_packing_records_use(self):
        for crop in ("carrots", "onions", "potatoes"):
            self.assertIn("U.S. No. 1", grades_for_crop(crop))
            self.assertIn("U.S. Commercial", grades_for_crop(crop))
        self.assertIn("U.S. No. 1", grades_for_crop("blueberries"))
        self.assertIn("U.S. No. 1", grades_for_crop("spinach"))

    def test_a_crop_with_no_usda_standard_is_offered_nothing(self):
        """No grade is better than a wrong grade — the same rule the template seeder follows
        when it refuses to give a crop another crop's operations."""
        for crop in ("hops", "pomegranates", "avocados", "cotton", "mixed_vegetables"):
            self.assertEqual(grades_for_crop(crop), (), f"{crop} is offered a grade it has no standard for")

    def test_an_unknown_crop_falls_through_to_nothing_rather_than_a_guess(self):
        self.assertEqual(grades_for_crop("dragonfruit"), ())
        self.assertEqual(grades_for_crop(None), ())
        self.assertEqual(grades_for_crop(""), ())

    def test_every_family_a_crop_points_at_actually_exists(self):
        for crop, family in CROP_GRADE_FAMILY.items():
            self.assertIn(family, GRADE_FAMILIES, f"{crop} points at family {family!r}, which does not exist")


class EveryCropIsMappedTests(SimpleTestCase):
    """A crop added to the catalogue must be given a family — or explicitly declared as having
    no USDA standard. Without this a new crop silently inherits `none` and its growers lose the
    picker with nobody noticing."""

    # The 33 active crop types as of 2026-08-21. Read from the seeder's own practice data so
    # the two cannot drift: a crop the seeder knows about is a crop a farmer can select.
    def test_every_crop_the_seeder_knows_about_has_a_grade_family(self):
        from carbon.management.commands.create_comprehensive_production_templates_v2 import CROP_CUSTOMIZATIONS

        unmapped = sorted(slug for slug in CROP_CUSTOMIZATIONS if slug not in CROP_GRADE_FAMILY)
        self.assertEqual(
            unmapped,
            [],
            f"crops with no grade family: {unmapped}. Map them, or map them to 'none' to say "
            "explicitly that the commodity has no USDA standard.",
        )


class TypeScriptMirrorTests(SimpleTestCase):
    """Two copies of a controlled vocabulary is how the original defect happened."""

    def _ts_source(self) -> str:
        self.assertTrue(TS_CATALOGUE.exists(), f"missing TS mirror at {TS_CATALOGUE}")
        return TS_CATALOGUE.read_text(encoding="utf-8")

    def test_every_grade_in_the_python_catalogue_is_in_the_typescript_one(self):
        source = self._ts_source()
        for family, grades in GRADE_FAMILIES.items():
            for grade in grades:
                self.assertIn(
                    f"'{grade}'",
                    source,
                    f"{family}/{grade!r} is missing from harvestGrades.ts — the forms would not offer it",
                )

    def test_every_crop_mapping_matches(self):
        source = self._ts_source()
        # `carrots: 'root_bulb'` — quoted only when the key needs it, which none of these do.
        pairs = dict(re.findall(r"^\s{2}([a-z_]+):\s*'([a-z_]+)',?$", source, re.M))
        for crop, family in CROP_GRADE_FAMILY.items():
            self.assertEqual(
                pairs.get(crop),
                family,
                f"harvestGrades.ts maps {crop!r} to {pairs.get(crop)!r}, Python maps it to {family!r}",
            )

    def test_the_column_width_agrees(self):
        """The TS side bounds the input with it. `History.finish()` assigns straight off the
        QueryDict with no serializer in the way, so an over-long typed grade would arrive at a
        varchar as a DATABASE error rather than a field message — the input is the only place
        that path can be bounded, and it can only be bounded correctly if the number matches."""
        self.assertIn(f"MAX_GRADE_LENGTH = {MAX_GRADE_LENGTH}", self._ts_source())

    def test_the_free_text_escape_agrees(self):
        source = self._ts_source()
        self.assertIn(f"OTHER_GRADE = '{OTHER_GRADE}'", source)
        self.assertIn(f"OTHER_GRADE_LABEL = '{OTHER_GRADE_LABEL}'", source)

    def test_the_legacy_labels_agree(self):
        source = self._ts_source()
        for slug in LEGACY_GRADE_LABELS:
            self.assertIn(f"{slug}:", source, f"legacy slug {slug!r} missing from the TS mirror")


class ThePacketPrintsWhatWasStoredTests(SimpleTestCase):
    def test_a_real_grade_prints_verbatim(self):
        """`.title()` over this column is what produced "Wa Extra Fancy" and "Us No. 1" on a
        live packet — neither is a grade, and a reviewer matching a lot against a packing
        record cannot find a silently re-cased abbreviation in a controlled vocabulary."""
        for grade in ("U.S. No. 1", "WA Extra Fancy", "U.S. Commercial", "U.S. Grade A (Fancy)"):
            self.assertEqual(_humanize_enum(grade), grade)

    def test_a_legacy_slug_still_renders_as_a_label(self):
        self.assertEqual(_humanize_enum("grade_a"), "Grade A")
        self.assertEqual(_humanize_enum("export_quality"), "Export Quality")

    def test_the_packet_never_prints_the_word_legacy_at_a_certifier(self):
        """`LEGACY_GRADE_LABELS` are notes to US. They exist so the PICKER can label a stored
        old value; they were briefly the model's `choices`, which meant
        `get_quality_grade_display()` would have printed "Grade A (legacy)" in the § 205.103
        Production Summary. The packet renders this column through `_humanize_enum`, which
        never sees that map."""
        for slug in LEGACY_GRADE_LABELS:
            rendered = _humanize_enum(slug) or ""
            self.assertNotIn("legacy", rendered.lower(), f"{slug!r} renders as {rendered!r}")

    def test_a_free_text_grade_survives_a_round_trip_to_the_packet(self):
        """End to end in one line: what the operator typed is what the reviewer reads."""
        typed = "Stemilt Fancy Pack"
        self.assertLessEqual(len(typed), MAX_GRADE_LENGTH)
        self.assertEqual(_humanize_enum(typed), typed)
