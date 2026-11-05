"""
The § 205.601 rows a certifier's form asks about carry the rule's own annotation, and only those are
offered as regulation wording.

WSDA AGR 2121 D4 and H5, OTCO C4 4.5-1 and WSDA AGR 2196's restrictions column ask how the
conditions on fixed coppers, copper sulfate, magnesium sulfate and micronutrients are met. The
catalogue held paraphrases for them ("Minimize soil accumulation.") and the boron row the wording
83 FR 66559 replaced in 2019, so no § 205.601 note could be printed as the rule's words. The eCFR
text (versioner API, up to date as of 2026-11-03) is held once in
`national_list_citations.ANNOTATIONS`; the seeder and migration 0071 write it.

Pinned here:
  * the held text is the post-2019 (j)(7) wording, and every held row is a row PARAGRAPHS cites;
  * the seeder and the migration store the same notes and effective dates;
  * regulation wording is offered for a held row, cited to the paragraph, and never for a
    descriptive § 205.601 note ("Per approved labeling.") or a held row edited since;
  * `is_conditionally_permitted` is unchanged: a copper row is still not a § 205.602 condition;
  * the Materials List comment quotes a held row and stays silent on a descriptive one.
"""

import importlib
from datetime import date
from io import StringIO
from types import SimpleNamespace

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase

from certifications.models import NationalListSubstance, OrganicSystemPlan
from certifications.services.common_osp_workbooks import _material_listing_note
from certifications.services.material_restrictions import regulation_restriction
from certifications.services.national_list_citations import (
    ANNOTATION_EFFECTIVE,
    ANNOTATION_NOTES,
    ANNOTATIONS,
    PARAGRAPHS,
    held_annotation,
)
from company.models import Company, Establishment

COPPER = "Copper hydroxide"
BORON = "Soluble boron products"


def _seed():
    call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())


def _row(name):
    return NationalListSubstance.objects.get(cfr_section="205.601", substance_name=name)


class HeldTextTests(TestCase):
    def test_the_micronutrient_annotation_is_the_wording_in_force_since_2019(self):
        _, text = ANNOTATIONS[("205.601", BORON)]
        self.assertIn("other documented and verifiable method as approved by the certifying agent", text)
        self.assertNotIn("Soil deficiency must be documented by testing", text)
        self.assertEqual(ANNOTATION_EFFECTIVE["(j)(7)"], date(2019, 1, 28))

    def test_every_held_row_is_a_row_the_rule_cites_under_that_paragraph(self):
        for key, (paragraph, text) in ANNOTATIONS.items():
            self.assertIn(key, PARAGRAPHS, key)
            self.assertTrue(PARAGRAPHS[key][0].startswith(paragraph), (key, paragraph))
            self.assertIn("—", text, key)
            # The stored condition is the rule's words, only its first letter capitalised.
            note = ANNOTATION_NOTES[key]
            self.assertTrue(note in text or note[:1].lower() + note[1:] in text, key)

    def test_the_fixed_copper_condition_is_the_proviso_not_the_list_of_forms(self):
        """Review of back #310: the words after "Coppers, fixed" name the forms the entry covers."""
        note = ANNOTATION_NOTES[("205.601", COPPER)]
        self.assertEqual(
            note,
            "Copper-based materials must be used in a manner that minimizes accumulation in the soil and shall "
            "not be used as herbicides.",
        )


class SeederAndMigrationTests(TestCase):
    def test_the_seeder_stores_the_held_notes_and_dates(self):
        _seed()
        for (_, name), note in ANNOTATION_NOTES.items():
            row = _row(name)
            self.assertEqual(row.restriction_notes, note, name)
            self.assertEqual(row.effective_date, ANNOTATION_EFFECTIVE[ANNOTATIONS[("205.601", name)][0]], name)
            self.assertEqual(row.annotation_kind, NationalListSubstance.ANNOTATION_CONDITION, name)
        self.assertEqual(_row("Sucrose octanoate esters").restriction_notes, "Per approved labeling.")

    def test_the_migration_and_the_seeder_agree(self):
        _seed()
        seeded = {name: (_row(name).restriction_notes, _row(name).effective_date) for (_, name) in ANNOTATION_NOTES}
        # As production holds them before 0071: the old paraphrases, no date.
        for name in seeded:
            NationalListSubstance.objects.filter(pk=_row(name).pk).update(
                restriction_notes="Minimize soil accumulation.", effective_date=None
            )
        importlib.import_module("certifications.migrations.0071_national_list_205_601_annotations").store(apps, None)
        migrated = {name: (_row(name).restriction_notes, _row(name).effective_date) for name in seeded}
        self.assertEqual(migrated, seeded)

    def test_the_migration_creates_nothing(self):
        NationalListSubstance.objects.all().delete()
        importlib.import_module("certifications.migrations.0071_national_list_205_601_annotations").store(apps, None)
        self.assertFalse(NationalListSubstance.objects.exists())


class RegulationWordingTests(TestCase):
    def setUp(self):
        _seed()
        company = Company.objects.create(name="Cashmere Orchards LLC")
        est = Establishment.objects.create(name="Cashmere", company=company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(establishment=est, version_number=1, status="draft")

    def test_a_held_row_is_offered_cited_to_its_paragraph(self):
        copper = _row(COPPER)
        held = regulation_restriction(self.osp, "national_list", copper.pk)
        self.assertIsNotNone(held)
        self.assertEqual(held["citation"], "§ 205.601(i)(2)")
        self.assertEqual(held["text"], ANNOTATION_NOTES[("205.601", COPPER)])
        boron = regulation_restriction(self.osp, "national_list", _row(BORON).pk)
        self.assertEqual(boron["citation"], "§ 205.601(j)(7)")
        self.assertEqual(boron["effective_date"], date(2019, 1, 28))

    def test_a_descriptive_note_is_never_offered_as_the_rule(self):
        self.assertIsNone(regulation_restriction(self.osp, "national_list", _row("Sucrose octanoate esters").pk))

    def test_a_held_row_edited_since_is_not_offered(self):
        copper = _row(COPPER)
        NationalListSubstance.objects.filter(pk=copper.pk).update(restriction_notes="Minimize soil accumulation.")
        self.assertIsNone(held_annotation(_row(COPPER)))
        self.assertIsNone(regulation_restriction(self.osp, "national_list", copper.pk))

    def test_a_copper_row_is_still_not_a_section_602_condition(self):
        self.assertFalse(_row(COPPER).is_conditionally_permitted)
        self.assertFalse(_row("Magnesium sulfate").is_conditionally_permitted)


class MaterialsListCommentTests(TestCase):
    def setUp(self):
        _seed()

    def _note(self, name):
        plan = SimpleNamespace(source="National List", source_id=_row(name).pk)
        return _material_listing_note(SimpleNamespace(event=None, plan=plan))

    def test_a_held_row_is_quoted_with_its_paragraph(self):
        self.assertEqual(
            self._note("Magnesium sulfate"),
            "National List § 205.601(j)(6) Magnesium sulfate: Allowed with a documented soil deficiency.",
        )

    def test_a_descriptive_row_is_not_quoted(self):
        self.assertIsNone(self._note("Sucrose octanoate esters"))
