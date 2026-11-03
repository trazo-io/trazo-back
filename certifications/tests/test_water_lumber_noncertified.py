"""Irrigation water, treated lumber and the non-organic side (2026.11.09).

CCOF G6.0 D1/D2/D4/D4a/D5 and OTCO C9 9.2-1 ask where irrigation water comes from and whether lines or
tailwater are shared with cropland where prohibited materials go into the water. CCOF G6.0 B1/B2 and
OTCO C9 9.3-4 ask about treated lumber present or planned and the replacement policy. OTCO 9.4-1 asks
what a split operation's non-organic side grows, and WSDA AGR 2121 L 10/10a asks about post-harvest
inputs used only on non-certified crops. Each was unasked or free text before.
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import missing_required, visible_questions
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from product.models import Parcel

AT = "2026-11-09T10:00:00+00:00"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _visible(module_key, answers):
    return {q.key for _p, q in visible_questions(MODULES_BY_KEY[module_key], answers)}


class _Plan(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Water Lumber Co")
        self.est = Establishment.objects.create(name="Creek Orchard", company=company, state="WA")

    def plan(self, modules):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name="CCOF Certification Services, LLC",
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {
                    key: {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}
                    for key, answers in modules.items()
                },
            },
        )

    def row(self, osp, agent, code, ref):
        form = next(f for f in load_forms(agent) if f.code == code)
        return next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == ref)


class GatesTests(_Plan):
    def test_shared_lines_are_asked_until_the_farm_says_it_does_not_irrigate(self):
        self.assertIn("shared_irrigation_with_prohibited", _visible("g4_2_natural_resources", {}))
        self.assertNotIn(
            "shared_irrigation_with_prohibited",
            _visible("g4_2_natural_resources", {"irrigation_source_types": ["not_irrigated"]}),
        )

    def test_names_are_asked_for_a_district_or_a_river(self):
        self.assertIn(
            "irrigation_source_names",
            _visible("g4_2_natural_resources", {"irrigation_source_types": ["irrigation_district"]}),
        )
        self.assertNotIn(
            "irrigation_source_names", _visible("g4_2_natural_resources", {"irrigation_source_types": ["well"]})
        )

    def test_saying_not_irrigated_later_hides_every_answer_given_under_irrigation(self):
        stale = {
            "irrigation_source_types": ["not_irrigated"],
            "water_quality_tested": True,
            "water_from_irrigation_district": True,
            "irrigation_district_additives": "yes",
            "shared_irrigation_with_prohibited": True,
            "shared_irrigation_mitigation": "Backflow valve on the organic lateral.",
        }
        children = {
            "water_quality_test_frequency",
            "irrigation_district_additives",
            "irrigation_district_mitigation",
            "irrigation_district_documentation",
            "shared_irrigation_responsible",
            "shared_irrigation_mitigation",
            "irrigation_piping_map_upload",
        }
        self.assertEqual(children & _visible("g4_2_natural_resources", stale), set())
        self.assertEqual(children & set(missing_required(MODULES_BY_KEY["g4_2_natural_resources"], stale)), set())

    def test_the_piping_diagram_is_asked_on_the_district_branch_without_shared_lines(self):
        district_only = {
            "irrigation_source_types": ["irrigation_district"],
            "water_from_irrigation_district": True,
            "irrigation_district_additives": "yes",
            "shared_irrigation_with_prohibited": False,
        }
        visible = _visible("g4_2_natural_resources", district_only)
        self.assertIn("irrigation_district_piping_map_upload", visible)
        self.assertNotIn("irrigation_piping_map_upload", visible)
        no_additives = {**district_only, "irrigation_district_additives": "no"}
        self.assertNotIn("irrigation_district_piping_map_upload", _visible("g4_2_natural_resources", no_additives))

    def test_the_lumber_other_text_goes_with_the_lumber(self):
        stale = {"treated_lumber_any": False, "treated_lumber_policy": ["other"]}
        self.assertNotIn("treated_lumber_policy_other", _visible("g6_0_production", stale))

    def test_the_lumber_policy_and_the_non_organic_crops_follow_their_gates(self):
        self.assertNotIn("treated_lumber_policy", _visible("g6_0_production", {"treated_lumber_any": False}))
        self.assertIn("treated_lumber_policy", _visible("g6_0_production", {"treated_lumber_any": True}))
        self.assertNotIn("nonorganic_crops_products", _visible("g6_0_production", {"split_operation": False}))
        self.assertIn("nonorganic_crops_products", _visible("g6_0_production", {"split_operation": True}))


class ThePlanPrintsThemTests(_Plan):
    def test_shared_lines_print_with_who_applies_and_how_contact_is_prevented(self):
        osp = self.plan(
            {
                "g4_2_natural_resources": {
                    "irrigation_source_types": ["irrigation_district"],
                    "irrigation_source_names": "Wenatchee Reclamation District",
                    "shared_irrigation_with_prohibited": True,
                    "shared_irrigation_responsible": False,
                    "shared_irrigation_mitigation": "Backflow valve on the organic lateral.",
                }
            }
        )
        text = _text(generate_module_pdf(osp, "g4_2_natural_resources"))
        self.assertIn("Wenatchee Reclamation District", text)
        self.assertIn("Backflow valve on the organic lateral.", text)

    def test_a_stale_shared_line_answer_does_not_print_once_the_farm_does_not_irrigate(self):
        osp = self.plan(
            {
                "g4_2_natural_resources": {
                    "irrigation_source_types": ["not_irrigated"],
                    "shared_irrigation_with_prohibited": True,
                    "shared_irrigation_mitigation": "Backflow valve on the organic lateral.",
                }
            }
        )
        self.assertNotIn("Backflow valve", _text(generate_module_pdf(osp, "g4_2_natural_resources")))

    def test_no_post_harvest_input_only_on_noncertified_crops_claims_nothing_wider(self):
        osp = self.plan({"g6_4_handling": {"handling_activities": ["packing"], "noncertified_only_inputs_used": False}})
        text = _text(generate_module_pdf(osp, "g6_4_handling"))
        self.assertNotIn("whatever the crop", text)
        compiled = MODULES_BY_KEY["g6_4_handling"]
        rule = next(
            q for p in compiled.pages for q in p.questions if q.key == "noncertified_only_inputs_used"
        ).compiles_to
        self.assertEqual(rule.template_false, "No post-harvest input is used only on non-certified crops.")

    def test_no_treated_lumber_beside_a_parcel_that_has_it_prints_review(self):
        Parcel.objects.create(name="Block 4", establishment=self.est, area=3.0, treated_lumber_present=True)
        Parcel.objects.create(name="Block 5", establishment=self.est, area=3.0)
        osp = self.plan({"g6_0_production": {"treated_lumber_any": False}})
        text = _text(generate_module_pdf(osp, "g6_0_production"))
        self.assertIn(
            "[REVIEW] The parcel application for Block 4 says treated lumber is in contact with crops or soil.", text
        )
        self.assertNotIn("Block 5", text)

    def test_no_treated_lumber_with_no_parcel_contradiction_prints_no_review(self):
        Parcel.objects.create(name="Block 5", establishment=self.est, area=3.0)
        osp = self.plan({"g6_0_production": {"treated_lumber_any": False}})
        self.assertNotIn("[REVIEW] The parcel application", _text(generate_module_pdf(osp, "g6_0_production")))

    def test_page_e_prints_the_lumber_policy(self):
        osp = self.plan(
            {
                "g6_0_production": {
                    "treated_lumber_any": True,
                    "treated_lumber_policy": ["metal_stakes"],
                    "treated_lumber_planned_installations": "Steel trellis posts for the 2027 block.",
                }
            }
        )
        text = _text(generate_module_pdf(osp, "g6_0_production"))
        self.assertIn("E. Treated lumber", text)
        self.assertIn("We use metal stakes and posts", text)
        self.assertIn("Steel trellis posts for the 2027 block.", text)


class CoverageTests(_Plan):
    def test_ccof_d4_is_answered_by_the_shared_lines_answer_and_does_not_apply_without_irrigation(self):
        answered = self.plan({"g4_2_natural_resources": {"shared_irrigation_with_prohibited": False}})
        self.assertEqual(self.row(answered, "ccof", "G6.0", "D4").state, "answered")
        dry = self.plan({"g4_2_natural_resources": {"irrigation_source_types": ["not_irrigated"]}})
        self.assertEqual(self.row(dry, "ccof", "G6.0", "D4").state, "not_applicable")
        self.assertEqual(self.row(dry, "ccof", "G6.0", "D1").state, "answered")

    def test_ccof_d5_is_answered_on_the_district_branch_alone(self):
        osp = self.plan(
            {
                "g4_2_natural_resources": {
                    "irrigation_source_types": ["irrigation_district"],
                    "water_from_irrigation_district": True,
                    "irrigation_district_additives": "yes",
                    "irrigation_district_mitigation": "Head gate closed 48 hours after each district treatment.",
                    "shared_irrigation_with_prohibited": False,
                }
            }
        )
        self.assertEqual(self.row(osp, "ccof", "G6.0", "D5").state, "answered")

    def test_ccof_b2_does_not_apply_without_treated_lumber(self):
        osp = self.plan({"g6_0_production": {"treated_lumber_any": False}})
        self.assertEqual(self.row(osp, "ccof", "G6.0", "B1").state, "answered")
        self.assertEqual(self.row(osp, "ccof", "G6.0", "B2").state, "not_applicable")

    def test_wsda_l10_reads_the_g6_4_answer(self):
        osp = self.plan({"g6_4_handling": {"handling_activities": ["packing"], "noncertified_only_inputs_used": False}})
        self.assertEqual(self.row(osp, "wsda", "L", "10").state, "answered")
        self.assertEqual(self.row(osp, "wsda", "L", "10a").state, "not_applicable")

    def test_otco_9_4_1_names_the_non_organic_side(self):
        osp = self.plan(
            {"g6_0_production": {"split_operation": True, "nonorganic_crops_products": "Conventional Gala, block 9."}}
        )
        self.assertEqual(self.row(osp, "otco", "C9", "9.4-1").state, "answered")
