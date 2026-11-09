"""G3.1 Container & Greenhouse/Shadehouse Production (CCOF ORGB46; content 2026.11.27).

CCOF asks every operation for G3.1, even if only to say "None of these". Trazo had no G3.1, so the packet said
nothing where CCOF expects the form or its not-applicable box. The module's not-applicable attestation is that box;
each later section opens on the answer that makes it apply, as the form's "Skip to" lines do; and a G3.1 marked not
applicable prints a [REVIEW] line for each fact elsewhere that says otherwise.
"""

import io

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_pages, visible_questions
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.structure_production import na_contradictions
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel

G31 = MODULES_BY_KEY["g3_1_container_greenhouse"]
AT = "2026-11-09T10:00:00Z"


def _shown(answers):
    return {q.key for _p, q in visible_questions(G31, answers)}


def _pages(answers):
    return {p.key for p in visible_pages(G31, answers)}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class ShapeTests(SimpleTestCase):
    def test_it_is_g3_1_and_its_not_applicable_box_is_none_of_these(self):
        self.assertEqual(G31.code, "G3.1")
        self.assertTrue(G31.allows_not_applicable)
        self.assertIn("None of these", G31.na_label["en"])

    def test_a1_offers_the_seven_production_types(self):
        question = next(q for p in G31.pages for q in p.questions if q.key == "structure_production_types")
        self.assertEqual(
            [o.value for o in question.options],
            [
                "annual_seedlings",
                "potted_planting_stock",
                "edible_sprouts",
                "microgreens",
                "mushrooms",
                "container_crops",
                "in_ground_in_structures",
            ],
        )


class SkipsTests(SimpleTestCase):
    def test_container_systems_open_only_on_container_crops(self):
        self.assertNotIn("b4_container_systems", _pages({"structure_production_types": ["annual_seedlings"]}))
        self.assertIn("b4_container_systems", _pages({"structure_production_types": ["container_crops"]}))

    def test_sprout_questions_open_only_on_sprouts(self):
        self.assertNotIn("sprout_seed_always_organic", _shown({"structure_production_types": ["microgreens"]}))
        self.assertIn("sprout_seed_always_organic", _shown({"structure_production_types": ["edible_sprouts"]}))

    def test_section_c_follows_its_own_stops(self):
        self.assertEqual(
            {"organic_in_structures"} & _shown({"organic_in_structures": False}), {"organic_in_structures"}
        )
        self.assertNotIn("nonorganic_in_structures", _shown({"organic_in_structures": False}))
        only_organic = _shown({"organic_in_structures": True, "nonorganic_in_structures": False})
        self.assertNotIn("shared_irrigation_contact", only_organic)
        both = _shown({"organic_in_structures": True, "nonorganic_in_structures": True})
        self.assertTrue(
            {"organic_area_identification", "shared_ventilation_drift", "shared_irrigation_contact"} <= both
        )

    def test_section_d_opens_only_on_alternating_production(self):
        dedicated = {
            "organic_in_structures": True,
            "nonorganic_in_structures": True,
            "nonorganic_structure_arrangement": ["dedicated_areas"],
        }
        self.assertNotIn("d_alternating", _pages(dedicated))
        alternating = {**dedicated, "nonorganic_structure_arrangement": ["alternating_production"]}
        self.assertIn("d_alternating", _pages(alternating))


class _Plan(TestCase):
    def setUp(self):
        self.est = Establishment.objects.create(name="Nursery Row", company=Company.objects.create(name="Nursery"))
        self.parcel = Parcel.objects.create(name="Home Block", establishment=self.est, area=3.0)

    def plan(self, modules):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": modules},
        )

    @staticmethod
    def answered(answers):
        return {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}

    @staticmethod
    def na():
        return {"answers": {}, "not_applicable": True, "na_attestation": {"by": None, "at": AT}}


class NotApplicableTests(_Plan):
    def test_a_clean_none_of_these_prints_no_review(self):
        osp = self.plan({"g3_1_container_greenhouse": self.na()})
        self.assertEqual(na_contradictions(osp), [])
        page = _text(generate_module_pdf(osp, "g3_1_container_greenhouse"))
        self.assertIn("Not applicable", page)
        self.assertIn("None of these", page)
        self.assertNotIn("[REVIEW]", page)

    def test_each_fact_that_says_otherwise_prints_a_review(self):
        self.parcel.container_production = True
        self.parcel.save(update_fields=["container_production"])
        History.objects.create(name="Starts", start_date=timezone.now(), parcel=self.parcel, is_outdoor=False)
        osp = self.plan(
            {
                "g3_1_container_greenhouse": self.na(),
                "g3_0_seeds": self.answered({"seedlings_used": ["own_organic"]}),
                "g3_2_planting_stock": self.answered({"stock_sold_as_organic": "sold_organic_stock"}),
                "g4_0_rotation_soil": self.answered({"system_type": ["perennial", "container"]}),
            }
        )
        lines = na_contradictions(osp)
        self.assertEqual(len(lines), 5, lines)
        page = _text(generate_module_pdf(osp, "g3_1_container_greenhouse"))
        for words in (
            "G3.0 states the operation grows its own organic seedlings",
            "G3.0b states the operation sells planting stock as organic",
            "G4.0 names a container production system",
            "recorded as container or greenhouse production: Home Block",
            "1 production is recorded as indoor",
        ):
            self.assertIn(words, page)

    def test_a_module_marked_not_applicable_elsewhere_is_not_read_as_a_contradiction(self):
        osp = self.plan(
            {
                "g3_1_container_greenhouse": self.na(),
                "g3_0_seeds": {**self.answered({"seedlings_used": ["own_organic"]}), "not_applicable": True},
            }
        )
        self.assertEqual(na_contradictions(osp), [])


class OnThePageTests(_Plan):
    def test_answers_print_under_their_sections_with_the_reviews_options_carry(self):
        osp = self.plan(
            {
                "g3_1_container_greenhouse": self.answered(
                    {
                        "structure_production_types": ["annual_seedlings"],
                        "annual_seedlings_use": ["on_farm_use"],
                        "locations_within_certified_parcel": "no",
                        "uses_growing_media": "yes",
                        "growing_media_components_listed": True,
                        "growing_media_new_each_cycle": "yes",
                        "growing_media_disposal": ["composted_onsite"],
                        "irrigation_effluent_management": ["recaptured_reused"],
                        "organic_in_structures": True,
                        "nonorganic_in_structures": True,
                        "nonorganic_structure_arrangement": ["dedicated_areas"],
                        "organic_area_identification": ["clear_signage"],
                        "organic_plant_distinction": ["tray_plant_tags"],
                        "media_fertility_commingling_prevention": ["cleanout_sop"],
                        "shared_ventilation_drift": ["no_shared_ventilation"],
                        "shared_irrigation_contact": ["no_shared_irrigation"],
                    }
                )
            }
        )
        page = _text(generate_module_pdf(osp, "g3_1_container_greenhouse"))
        for words in (
            "A. Production types and locations",
            "Annual seedlings (e.g. tomato transplants",
            "For on-farm use",
            "[REVIEW] A growing location is outside the certified parcels",
            "B. Production materials and practices",
            "Composted on site",
            "C. Nonorganic production in greenhouses, shadehouses and buildings",
            "Clear signage",
            "Not applicable, no shared irrigation systems",
        ):
            self.assertIn(words, page)
        # "SOP attached" with no file is a claim the page must not let stand.
        self.assertIn("[REVIEW]", page[page.index("Standard Operating Procedure") :])
        # A section the answers close prints its heading with the answer that closes it, never the questions.
        self.assertIn("D. Alternating production Does not apply: asked only when", page)
        self.assertNotIn("alternating production you want", page)


class ReviewFindingsTests(_Plan):
    """Review of back #361."""

    def test_a_sanitizer_not_on_the_list_is_answerable_and_asks_the_procedure(self):
        question = next(q for p in G31.pages for q in p.questions if q.key == "sprout_seed_sanitizers")
        option = next(o for o in question.options if o.value == "not_listed")
        self.assertIn("not on the materials list", option.review)
        shown = _shown({"structure_production_types": ["edible_sprouts"], "sprout_seed_sanitizers": "not_listed"})
        self.assertIn("sprout_seed_sanitizing_procedure", shown)

    def test_in_ground_in_structures_against_no_organic_production_in_structures_prints_a_review(self):
        osp = self.plan(
            {
                "g3_1_container_greenhouse": self.answered(
                    {"structure_production_types": ["in_ground_in_structures"], "organic_in_structures": False}
                )
            }
        )
        page = _text(generate_module_pdf(osp, "g3_1_container_greenhouse"))
        self.assertIn("[REVIEW] A1 says crops are grown in the ground within greenhouses", page)
        consistent = self.plan(
            {
                "g3_1_container_greenhouse": self.answered(
                    {"structure_production_types": ["annual_seedlings"], "organic_in_structures": False}
                )
            }
        )
        self.assertNotIn("[REVIEW] A1 says", _text(generate_module_pdf(consistent, "g3_1_container_greenhouse")))


class RegisterRowsTests(TestCase):
    def test_every_row_is_covered_and_the_form_declares_the_module(self):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms("ccof") if f.code == "G3.1")
        self.assertIn("g3_1_container_greenhouse", form.trazo_modules)
        self.assertEqual({i.status for i in form.items}, {"covered"})
