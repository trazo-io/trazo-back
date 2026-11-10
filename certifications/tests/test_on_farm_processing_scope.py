"""On-farm processing scope (content 2026.11.30).

OTCO C7 7.3-1 lists processing steps G6.4 had no option for (freezing, cutting, cooking, mixing, fermenting, seed
cleaning); 7.3-2 and 7.3-3 ask whether products carry off-farm ingredients and whether non-organic product is processed
at the facility; 7.4-1 and WSDA L 6 ask whether the handling area or equipment is shared; CCOF G6.4's applicability gate
names four cases where the form does not apply. Each is a certification-scope fact the agent acts on.
"""

import io

from django.test import SimpleTestCase, TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_questions
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment

G64 = MODULES_BY_KEY["g6_4_handling"]
AT = "2026-11-10T10:00:00Z"


def _question(key):
    return next(q for p in G64.pages for q in p.questions if q.key == key)


def _shown(answers):
    return {q.key for _p, q in visible_questions(G64, answers)}


class OptionsTests(SimpleTestCase):
    def test_otcos_processing_steps_are_options(self):
        values = {o.value for o in _question("handling_activities").options}
        self.assertTrue({"freezing", "cutting", "cooking", "mixing", "fermenting", "seed_cleaning"} <= values)

    def test_every_disqualifier_prints_a_review_and_none_is_exclusive(self):
        options = {o.value: o for o in _question("simple_handling_disqualifiers").options}
        for value in (
            "nonorganic_handled_here",
            "off_farm_ingredients",
            "multi_ingredient_products",
            "multi_farm_csa",
            "complex_handling",
        ):
            self.assertIn("the certifying agent decides whether this needs", options[value].review)
        self.assertTrue(options["none"].exclusive)

    def test_otcos_two_commingling_controls_are_options(self):
        values = {o.value for o in _question("commingling_controls").options}
        self.assertTrue({"organic_first", "separate_storage_areas"} <= values)


class ReviewFindingsTests(SimpleTestCase):
    """Review of back #366."""

    def test_each_disqualifier_review_names_its_own_case(self):
        reviews = [o.review for o in _question("simple_handling_disqualifiers").options if o.review]
        self.assertEqual(len(reviews), len(set(reviews)), "two disqualifiers print the same line")

    def test_freezing_is_named_once(self):
        labels = [o.label["en"].lower() for o in _question("handling_activities").options]
        self.assertEqual(sum("freezing" in label for label in labels), 1, labels)


class GateTests(SimpleTestCase):
    def test_scope_is_asked_once_a_handling_step_is_named(self):
        self.assertNotIn("simple_handling_disqualifiers", _shown({"handling_activities": ["no_onfarm_handling"]}))
        self.assertIn("simple_handling_disqualifiers", _shown({"handling_activities": ["cooking"]}))


class OnThePageTests(TestCase):
    def test_a_disqualifier_prints_its_review_and_the_shared_answer_prints(self):
        est = Establishment.objects.create(name="Jam Kitchen", company=Company.objects.create(name="Jam"))
        answers = {
            "handling_activities": ["cooking", "mixing"],
            "simple_handling_disqualifiers": ["off_farm_ingredients"],
            "shares_handling_area_or_equipment": True,
        }
        osp = OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {"g6_4_handling": {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}},
            },
        )
        page = " ".join(extract_text(io.BytesIO(generate_module_pdf(osp, "g6_4_handling"))).split())
        self.assertIn("Cooking", page)
        self.assertIn("Products made here contain ingredients from off the farm (other than salt)", page)
        self.assertIn(
            "[REVIEW] Products made here contain ingredients from off the farm; the certifying agent decides", page
        )
        self.assertIn("used for both organic and non-organic crops? Yes", page)


class RegisterRowsTests(SimpleTestCase):
    def test_the_rows_are_covered(self):
        for agent, code, refs in (
            ("otco", "C7", ("7.3-1", "7.3-2", "7.3-3", "7.3-4", "7.4-1")),
            ("wsda", "L", ("3", "6")),
            ("ccof", "G6.4", ("Preamble (applicability)",)),
        ):
            form = next(
                f
                for f in load_forms(agent)
                if code in (f.code, f.document_id) or f.path.stem.startswith(f"2121-{code}-")
            )
            for ref in refs:
                self.assertEqual(next(i for i in form.items if i.ref == ref).status, "covered", (agent, ref))
