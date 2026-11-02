"""Compost and manure: what CCOF G4.1, OTCO C4 and WSDA AGR 2121 D ask (2026.11.02).

WHY THIS EXISTS
---------------
* A grazed orchard told G5.0 it grazes and told G4.1 "none of these are used", so the § 205.203(c)(1)
  interval and the water-protection answer never appeared for it.
* The interval rule was one choice, though all three agents say "all that apply": a farm with root
  crops and tree fruit could state only one. Migration 0060 wraps stored answers losslessly.
"""

import importlib

from django.apps import apps as django_apps
from django.test import SimpleTestCase, TestCase

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_questions
from company.models import Company, Establishment

G41 = "g4_1_compost_manure"
MIGRATION = importlib.import_module("certifications.migrations.0060_manure_interval_multichoice")


def _envelope(value):
    return {"at": "2026-08-21T11:28:46+00:00", "value": value}


def _visible(answers):
    return {q.key for _page, q in visible_questions(MODULES_BY_KEY[G41], answers)}


class PlannedGrazingTests(SimpleTestCase):
    def test_planned_grazing_alone_opens_the_interval_and_water_questions(self):
        keys = _visible({"materials_applied": _envelope(["planned_grazing"])})
        self.assertIn("raw_manure_interval_rule", keys)
        self.assertIn("raw_manure_water_risk", keys)
        # Where the manure comes from is a question about APPLIED manure only.
        self.assertNotIn("raw_manure_source", keys)

    def test_no_manure_and_no_grazing_keeps_the_page_closed(self):
        keys = _visible({"materials_applied": _envelope(["purchased_compost"])})
        self.assertNotIn("raw_manure_interval_rule", keys)

    def test_the_water_answer_is_required_where_it_shows(self):
        question = next(
            q for page in MODULES_BY_KEY[G41].pages for q in page.questions if q.key == "raw_manure_water_risk"
        )
        self.assertTrue(question.required)


class IntervalRuleShapeTests(SimpleTestCase):
    def test_the_interval_rule_is_all_that_apply(self):
        question = next(
            q for page in MODULES_BY_KEY[G41].pages for q in page.questions if q.key == "raw_manure_interval_rule"
        )
        self.assertEqual(question.kind, "checkbox_group")
        self.assertIn("processed_meets_5006", {o.value for o in question.options})


class MigrationTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Manure Co")
        self.est = Establishment.objects.create(name="Manure Farm", company=company, state="OR")

    def _plan(self, version, status, **answers):
        osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=version, status=status)
        osp.module_responses = {"modules": {G41: {"answers": {k: _envelope(v) for k, v in answers.items()}}}}
        osp.save(update_fields=["module_responses"])
        return osp

    def _answers(self, osp):
        osp.refresh_from_db()
        return osp.module_responses["modules"][G41]["answers"]

    def test_every_status_is_wrapped_and_nothing_else_moves(self):
        plans = [
            self._plan(i, status, raw_manure_interval_rule="contact_120_days", materials_applied=["raw_manure"])
            for i, status in enumerate(("draft", "submitted", "active", "superseded"), start=1)
        ]
        MIGRATION.wrap_scalars(django_apps, None)
        for osp in plans:
            answers = self._answers(osp)
            self.assertEqual(answers["raw_manure_interval_rule"]["value"], ["contact_120_days"], osp.status)
            self.assertEqual(answers["materials_applied"]["value"], ["raw_manure"])
            self.assertEqual(answers["raw_manure_interval_rule"]["at"], "2026-08-21T11:28:46+00:00")

    def test_a_list_is_left_alone_and_the_reverse_unwraps_only_one_item(self):
        several = self._plan(1, "draft", raw_manure_interval_rule=["contact_120_days", "no_contact_90_days"])
        one = self._plan(2, "draft", raw_manure_interval_rule="non_food_crop")
        MIGRATION.wrap_scalars(django_apps, None)
        self.assertEqual(
            self._answers(several)["raw_manure_interval_rule"]["value"], ["contact_120_days", "no_contact_90_days"]
        )
        MIGRATION.unwrap_single(django_apps, None)
        self.assertEqual(self._answers(one)["raw_manure_interval_rule"]["value"], "non_food_crop")
        self.assertEqual(len(self._answers(several)["raw_manure_interval_rule"]["value"]), 2)
