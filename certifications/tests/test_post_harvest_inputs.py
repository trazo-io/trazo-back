"""Inputs applied directly to crops after harvest (WSDA AGR 2121 §L 8, 9, 11).

L 8: "Does your business apply any inputs directly to any crops after harvest? Consider all inputs applied
to certified or non-certified crops." L 9: the types ("Anti-foaming agents / Anti-fungal agents / ... /
Waxes – coatings / Other"). L 11: "Describe how your business records each direct application of input
materials to both certified and non-certified products handled at your farm."
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules.conditions import visible_questions
from certifications.osp_modules.stubs import G6_4_HANDLING
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment

AT = "2026-11-07T12:00:00Z"
WSDA = "Washington State Department of Agriculture (WSDA)"
HANDLES = {"handling_activities": ["packing"]}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _visible(answers):
    return {q.key for _p, q in visible_questions(G6_4_HANDLING, answers)}


class Visibility(TestCase):
    def test_types_and_recording_hang_on_applying_inputs(self):
        shown = _visible({**HANDLES, "applies_post_harvest_inputs": True})
        self.assertTrue({"post_harvest_input_types", "post_harvest_input_recording"} <= shown)
        hidden = _visible({**HANDLES, "applies_post_harvest_inputs": False, "post_harvest_input_types": ["other"]})
        self.assertFalse({"post_harvest_input_types", "post_harvest_input_types_other"} & hidden)

    def test_the_other_text_needs_the_other_box(self):
        self.assertNotIn(
            "post_harvest_input_types_other",
            _visible({**HANDLES, "applies_post_harvest_inputs": True, "post_harvest_input_types": ["waxes_coatings"]}),
        )

    def test_livestock_feed_inputs_are_not_offered(self):
        q = next(q for p in G6_4_HANDLING.pages for q in p.questions if q.key == "post_harvest_input_types")
        values = {o.value for o in q.options}
        self.assertNotIn("feed_antibiotics", values)
        self.assertIn("waxes_coatings", values)
        self.assertIn("sprouting_inhibitors", values)

    def test_all_are_optional(self):
        questions = {q.key: q for p in G6_4_HANDLING.pages for q in p.questions}
        for key in (
            "applies_post_harvest_inputs",
            "post_harvest_input_types",
            "post_harvest_input_types_other",
            "post_harvest_input_recording",
        ):
            self.assertFalse(questions[key].required, key)


class OnThePage(TestCase):
    def plan(self, answers, certifier=WSDA):
        est = Establishment.objects.create(name="Wax Farm", company=Company.objects.create(name="Wax LLC"))
        return OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            certifier_name=certifier,
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {"g6_4_handling": {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}},
            },
        )

    def test_the_answers_print_on_g6_4(self):
        osp = self.plan(
            {
                **HANDLES,
                "applies_post_harvest_inputs": True,
                "post_harvest_input_types": ["waxes_coatings", "other"],
                "post_harvest_input_types_other": "1-MCP in storage rooms",
                "post_harvest_input_recording": "Packing-line log names the wax, lot and date",
            }
        )
        page = _text(generate_module_pdf(osp, "g6_4_handling"))
        self.assertIn("Do you apply any input directly to crops after harvest", page)
        self.assertIn("Waxes or coatings", page)
        self.assertIn("1-MCP in storage rooms", page)
        self.assertIn("Packing-line log names the wax, lot and date", page)

    def test_wsda_l_8_reads_answered(self):
        osp = self.plan({**HANDLES, "applies_post_harvest_inputs": False})
        form = next(f for f in load_forms("wsda") if f.code == "L")
        row = next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == "8")
        self.assertEqual(row.state, "answered")
