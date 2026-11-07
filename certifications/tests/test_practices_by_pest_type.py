"""Preventive practices by the pest they target, and `Question.retired`.

CCOF G5.0 §A asks 23 practices against four pest types (Weeds / Insects & invertebrates / Diseases & nematodes /
Vertebrate pests); WSDA AGR 2121 asks them in three sections (F 3 weeds, G 4 pests, H 3 diseases). G5.0 asks one
list per pest type. The untyped lists it replaced are retired: shown only to a plan that answered them, so an
answer already given keeps reading and printing as given, and no plan is asked it anew.
"""

import io

from django.test import SimpleTestCase, TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import missing_required, visible_questions
from certifications.osp_modules.schema import serialize_module
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment

AT = "2026-11-07T12:00:00Z"
G5 = MODULES_BY_KEY["g5_0_pest"]
TYPED = ("practices_weeds", "practices_insects", "practices_diseases", "practices_vertebrates")
RETIRED = ("prevention_practices", "weed_management_practices")


def _visible(answers):
    return {q.key for _p, q in visible_questions(G5, answers)}


class RetiredQuestion(SimpleTestCase):
    def test_a_new_plan_is_asked_the_typed_lists_not_the_retired_ones(self):
        shown = _visible({})
        self.assertTrue(set(TYPED) <= shown)
        self.assertFalse(set(RETIRED) & shown)

    def test_a_plan_that_answered_the_retired_lists_still_sees_them(self):
        shown = _visible({"prevention_practices": ["crop_rotation"], "weed_management_practices": ["mowing"]})
        self.assertTrue(set(RETIRED) <= shown)

    def test_a_retired_list_hides_its_other_box_when_unanswered(self):
        self.assertNotIn("prevention_practices_other", _visible({}))
        self.assertIn("prevention_practices_other", _visible({"prevention_practices": ["other"]}))

    def test_a_retired_required_question_never_blocks_completion(self):
        self.assertFalse(set(RETIRED) & set(missing_required(G5, {})))

    def test_the_flag_travels_to_the_app_only_where_set(self):
        payload = {q["key"]: q for p in serialize_module(G5)["pages"] for q in p["questions"]}
        self.assertTrue(payload["prevention_practices"]["retired"])
        self.assertNotIn("retired", payload["practices_weeds"])

    def test_each_typed_list_offers_other_and_an_exclusive_none(self):
        questions = {q.key: q for p in G5.pages for q in p.questions}
        for key in TYPED:
            options = {o.value: o for o in questions[key].options}
            self.assertIn("other", options, key)
            self.assertTrue(options["none"].exclusive, key)
            self.assertFalse(questions[key].required, key)

    def test_the_forms_practices_are_offered_where_they_belong(self):
        questions = {q.key: {o.value for o in q.options} for p in G5.pages for q in p.questions}
        self.assertTrue(
            {"stale_seed_bed", "field_preparation", "crop_spacing", "flaming"} <= questions["practices_weeds"]
        )
        self.assertTrue(
            {"mating_disruption", "trap_crops", "companion_planting", "traps"} <= questions["practices_insects"]
        )
        self.assertTrue(
            {"vector_management", "microbial_products", "compost_tea", "soil_solarization"}
            <= questions["practices_diseases"]
        )
        self.assertTrue({"exclusion_barriers", "predator_habitat"} <= questions["practices_vertebrates"])


class OnThePage(TestCase):
    def plan(self, answers):
        est = Establishment.objects.create(name="Pest Farm", company=Company.objects.create(name="Pest LLC"))
        return OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {"g5_0_pest": {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}},
            },
        )

    def test_the_typed_lists_print_by_pest_type(self):
        page = _text(
            generate_module_pdf(
                self.plan({"practices_weeds": ["stale_seed_bed"], "practices_vertebrates": ["none"]}), "g5_0_pest"
            )
        )
        self.assertIn("Which practices does your operation use against weeds?", page)
        self.assertIn("Stale seed bed", page)
        self.assertIn("No practice is used against vertebrate pests", page)

    def test_a_retired_answer_still_prints_as_given(self):
        page = _text(generate_module_pdf(self.plan({"prevention_practices": ["crop_rotation"]}), "g5_0_pest"))
        self.assertIn("Crop rotation", page)
        self.assertIn("Which prevention and cultural practices does your operation use", page)

    def test_an_unanswered_retired_list_does_not_print(self):
        page = _text(generate_module_pdf(self.plan({}), "g5_0_pest"))
        self.assertNotIn("Which prevention and cultural practices does your operation use", page)


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())
