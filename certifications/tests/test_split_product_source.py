"""Where a split operation's non-organic product comes from, and the cover's product-types line.

§ 205.2: "Split operation. An operation that produces or handles both organic and nonorganic
agricultural products." A farm selling buffer-zone crop as non-organic is one, so its Yes stands;
what a reviewer could not read was that the buffer crop was the only non-organic product.
CCOF Certification Contract D1 and OTCO O1 A-2 ask "Both organic and nonorganic product(s) /
Organic product(s) only" on page one, and the packet cover never said it.
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import _packet_cover_pdf, generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment

AT = "2026-11-06T12:00:00Z"
CCOF = "California Certified Organic Farmers (CCOF)"
OTCO = "Oregon Tilth Certified Organic (OTCO)"
LABEL = "Organic and non-organic product:"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Plan(TestCase):
    def plan(self, g6_0=None, g2_0=None, certifier=CCOF, has_split_column=False):
        est = Establishment.objects.create(
            name="Buffer Farm",
            company=Company.objects.create(name="Buffer Farm LLC"),
            state="OR",
            has_split_operation=has_split_column,
        )
        modules = {}
        for key, answers in (("g6_0_production", g6_0), ("g2_0_fraud_prevention", g2_0)):
            if answers is not None:
                modules[key] = {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}
        return OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            certifier_name=certifier,
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": modules},
        )

    def cover(self, osp):
        return _text(_packet_cover_pdf(osp))

    def row(self, osp, agent, document_id, ref):
        form = next(f for f in load_forms(agent) if f.document_id == document_id)
        return next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == ref)


class SourceOnTheModulePage(_Plan):
    def test_a_buffer_only_farm_prints_its_source_and_keeps_its_yes(self):
        osp = self.plan(g6_0={"split_operation": True, "nonorganic_product_source": ["buffer_zone_crop"]})
        page = _text(generate_module_pdf(osp, "g6_0_production"))
        self.assertIn("Where does the non-organic product come from?", page)
        self.assertIn("Crop harvested from buffer zones, sold as non-organic", page)
        self.assertNotIn("Crops grown on parcels that are not certified organic", page)

    def test_the_other_source_prints_in_the_operators_words(self):
        osp = self.plan(
            g6_0={
                "split_operation": True,
                "nonorganic_product_source": ["other"],
                "nonorganic_product_source_other": "Culls given to a neighbor's cattle",
            }
        )
        self.assertIn("Culls given to a neighbor's cattle", _text(generate_module_pdf(osp, "g6_0_production")))

    def test_a_source_left_from_before_the_answer_changed_to_no_does_not_print(self):
        osp = self.plan(g6_0={"split_operation": False, "nonorganic_product_source": ["buffer_zone_crop"]})
        self.assertNotIn("buffer zones, sold as non-organic", _text(generate_module_pdf(osp, "g6_0_production")))

    def test_the_question_is_optional(self):
        from certifications.osp_modules.g6_0_production import G6_0_PRODUCTION

        questions = {q.key: q for p in G6_0_PRODUCTION.pages for q in p.questions}
        self.assertFalse(questions["nonorganic_product_source"].required)
        self.assertFalse(questions["nonorganic_product_source_other"].required)


class ProductTypesOnTheCover(_Plan):
    def test_a_buffer_only_farm_reads_both_with_the_buffer_source(self):
        osp = self.plan(g6_0={"split_operation": True, "nonorganic_product_source": ["buffer_zone_crop"]})
        self.assertIn(
            f"{LABEL} Both organic and nonorganic product(s) (non-organic product from: crop harvested from "
            "buffer zones, sold as non-organic)",
            self.cover(osp),
        )

    def test_several_sources_are_listed_in_the_forms_order(self):
        osp = self.plan(
            g6_0={"split_operation": True, "nonorganic_product_source": ["bought_in_nonorganic", "nonorganic_parcels"]}
        )
        self.assertIn(
            "non-organic product from: crops grown on parcels that are not certified organic; non-organic product "
            "bought from other operations and resold",
            self.cover(osp),
        )

    def test_a_yes_without_a_source_says_the_source_is_not_stated(self):
        osp = self.plan(g6_0={"split_operation": True})
        self.assertIn("the plan does not say where the non-organic product comes from", self.cover(osp))

    def test_no_reads_organic_only(self):
        text = self.cover(self.plan(g6_0={"split_operation": False}))
        self.assertIn(f"{LABEL} Organic product(s) only", text)
        self.assertNotIn("fraud-prevention answers", text)

    def test_no_against_a_g2_split_answer_is_flagged(self):
        osp = self.plan(g6_0={"split_operation": False}, g2_0={"fraud_risk_areas": ["split_production"]})
        self.assertIn("[REVIEW] The plan's fraud-prevention answers say the operation produces", self.cover(osp))

    def test_an_unanswered_plan_says_so(self):
        text = self.cover(self.plan(g6_0={}))
        self.assertIn(f"{LABEL} not stated in the plan", text)
        self.assertIn("[REVIEW] The plan does not say whether the operation produces or handles", text)

    def test_a_column_only_yes_from_before_the_binding_still_counts(self):
        self.assertIn(
            f"{LABEL} Both organic and nonorganic product(s)", self.cover(self.plan(g6_0={}, has_split_column=True))
        )


class RegisterRows(_Plan):
    def test_ccof_and_otco_page_one_questions_read_answered_from_the_plan(self):
        osp = self.plan(g6_0={"split_operation": True, "nonorganic_product_source": ["buffer_zone_crop"]})
        self.assertEqual(self.row(osp, "ccof", "ORGB06", "D1").state, "answered")
        osp_otco = self.plan(g6_0={"split_operation": False}, certifier=OTCO)
        self.assertEqual(self.row(osp_otco, "otco", "O1", "A-2").state, "answered")
