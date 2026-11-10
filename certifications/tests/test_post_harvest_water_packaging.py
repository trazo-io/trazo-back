"""Post-harvest water and packaging (content 2026.11.28).

OTCO C7 7.5-1b/c asks how water that is not municipal is shown potable and whether a test came back positive; WSDA L
14 and CCOF G6.1 B3a ask whether water treated on site still meets the Safe Drinking Water Act; CCOF G6.1 B3 asks
whether crops are washed in the field. OTCO C7 7.9-1 to 7.9-6 and WSDA L 16/17 ask what packaging touches the product,
the proof that it is untreated, non-GMO or food grade, and whether it is reused. None of it was asked.
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

G61 = MODULES_BY_KEY["g6_1_harvest_transport"]
G64 = MODULES_BY_KEY["g6_4_handling"]
AT = "2026-11-09T10:00:00Z"


#: G6.4's later pages open once the operation names a handling step.
HANDLES = {"handling_activities": ["washing"]}


def _shown(module, answers):
    if module is G64:
        answers = {**HANDLES, **answers}
    return {q.key for _p, q in visible_questions(module, answers)}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class WaterGatesTests(SimpleTestCase):
    def test_potability_is_asked_only_of_water_that_is_not_only_municipal(self):
        base = {"uses_water": True}
        self.assertNotIn(
            "post_harvest_water_potability", _shown(G64, {**base, "post_harvest_water_source": ["municipal"]})
        )
        well = _shown(G64, {**base, "post_harvest_water_source": ["municipal", "on_site_well"]})
        self.assertIn("post_harvest_water_potability", well)

    def test_testing_opens_the_positive_result_and_treatment_its_materials(self):
        shown = _shown(
            G64,
            {
                "uses_water": True,
                "post_harvest_water_source": ["on_site_well"],
                "post_harvest_water_potability": ["tested_regularly", "treated_sdwa"],
            },
        )
        self.assertTrue(
            {
                "post_harvest_water_positive_test",
                "post_harvest_water_test_results",
                "post_harvest_water_treatment_materials",
            }
            <= shown
        )

    def test_on_site_treatment_opens_the_safe_drinking_water_questions(self):
        self.assertNotIn("treated_water_meets_sdwa", _shown(G64, {"uses_water": True, "water_treated_onsite": False}))
        shown = _shown(G64, {"uses_water": True, "water_treated_onsite": True})
        self.assertTrue({"treated_water_meets_sdwa", "water_system_management"} <= shown)

    def test_where_crops_are_washed_is_asked_when_crop_washing_is_a_use(self):
        self.assertNotIn(
            "crop_wash_location", _shown(G64, {"uses_water": True, "post_harvest_water_uses": ["cooling"]})
        )
        self.assertIn(
            "crop_wash_location", _shown(G64, {"uses_water": True, "post_harvest_water_uses": ["crop_washing"]})
        )


class PackagingGatesTests(SimpleTestCase):
    def test_no_packaging_closes_every_follow_up(self):
        shown = _shown(G61, {"packaging_materials": ["none"]})
        self.assertFalse(
            {"packaging_contamination_safeguards", "single_use_packaging_food_grade_proof", "packaging_reused"} & shown
        )

    def test_each_proof_opens_on_its_own_material(self):
        self.assertIn("packaging_untreated_proof", _shown(G61, {"packaging_materials": ["twine"]}))
        self.assertNotIn("packaging_untreated_proof", _shown(G61, {"packaging_materials": ["glass"]}))
        self.assertIn("compostable_packaging_non_gmo_proof", _shown(G61, {"packaging_materials": ["compostable"]}))
        self.assertNotIn("compostable_packaging_non_gmo_proof", _shown(G61, {"packaging_materials": ["glass"]}))

    def test_every_proof_battery_has_a_truthful_answer_with_no_document(self):
        for key in (
            "packaging_untreated_proof",
            "compostable_packaging_non_gmo_proof",
            "single_use_packaging_food_grade_proof",
            "post_harvest_water_potability",
        ):
            module = G64 if key.startswith("post_harvest") else G61
            question = next(q for p in module.pages for q in p.questions if q.key == key)
            honest = [o for o in question.options if o.review and o.exclusive]
            self.assertTrue(honest, key)

    def test_reuse_asks_non_organic_contact_and_its_protection(self):
        shown = _shown(G61, {"packaging_materials": ["cardboard"], "packaging_reused": "yes"})
        self.assertIn("reused_packaging_held_nonorganic", shown)
        protected = _shown(
            G61,
            {
                "packaging_materials": ["cardboard"],
                "packaging_reused": "yes",
                "reused_packaging_held_nonorganic": "yes_protected",
            },
        )
        self.assertIn("reused_packaging_protection", protected)


class OnThePageTests(TestCase):
    def plan(self, module_key, answers):
        est = Establishment.objects.create(name="Wash Line", company=Company.objects.create(name="Wash"))
        return OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {module_key: {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}},
            },
        )

    def test_the_water_reviews_print(self):
        osp = self.plan(
            "g6_4_handling",
            {
                "handling_activities": ["washing"],
                "uses_water": True,
                "post_harvest_water_source": ["on_site_well"],
                "post_harvest_water_potability": ["tested_regularly"],
                "post_harvest_water_positive_test": "yes",
                "water_treated_onsite": True,
                "treated_water_meets_sdwa": "not_confirmed",
            },
        )
        page = _text(generate_module_pdf(osp, "g6_4_handling"))
        self.assertIn("[REVIEW] A test of the handling water came back positive for contaminants.", page)
        self.assertIn("[REVIEW] Water treated on site is not yet confirmed to meet the Safe Drinking Water Act.", page)

    def test_the_potability_review_claims_no_crop_contact(self):
        # Review of back #362: well water used only to rinse equipment reaches the question.
        osp = self.plan(
            "g6_4_handling",
            {
                "handling_activities": ["washing"],
                "uses_water": True,
                "post_harvest_water_uses": ["equipment_cleaning"],
                "post_harvest_water_source": ["on_site_well"],
                "post_harvest_water_potability": ["not_shown"],
            },
        )
        page = _text(generate_module_pdf(osp, "g6_4_handling"))
        self.assertIn("[REVIEW] Handling water from a non-municipal source is not shown to be potable.", page)
        self.assertNotIn("contacts the crop", page)

    def test_an_attached_proof_with_no_file_and_no_documentation_both_print_a_review(self):
        osp = self.plan(
            "g6_1_harvest_transport",
            {
                "packaging_materials": ["cardboard", "compostable"],
                "packaging_untreated_proof": ["letter_of_guarantee"],
                "compostable_packaging_non_gmo_proof": ["no_documentation"],
            },
        )
        page = _text(generate_module_pdf(osp, "g6_1_harvest_transport"))
        self.assertIn("A letter of guarantee from the manufacturer or supplier (attached below) [REVIEW]", page)
        self.assertIn("[REVIEW] Compostable or biodegradable packaging with no documentation that it is non-GMO.", page)


class RegisterRowsTests(SimpleTestCase):
    def test_the_rows_are_covered(self):
        for agent, code, refs in (
            ("otco", "C7", ("7.5-1b", "7.5-1c", "7.9-1", "7.9-2", "7.9-3", "7.9-4", "7.9-5", "7.9-6")),
            ("wsda", "L", ("14", "14a", "14b", "16", "17")),
            ("ccof", "G6.1", ("B3", "B3a")),
        ):
            form = next(
                f
                for f in load_forms(agent)
                if code in (f.code, f.document_id) or f.path.stem.startswith(f"2121-{code}-")
            )
            for ref in refs:
                self.assertEqual(next(i for i in form.items if i.ref == ref).status, "covered", (agent, ref))
