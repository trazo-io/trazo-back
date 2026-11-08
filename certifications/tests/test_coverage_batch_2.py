"""Content 2026.11.25: G3.0 page B on non-organic seed OR stock, and CCOF G6.0 A2's two attachments.

CCOF G3.0 §B and OTCO C3 3.3 apply to non-organic seed or non-organic planting stock. Page B opened on seed
alone, so an orchard planting non-organic nursery stock was never asked. `ModulePage.visible_when_any` is the
OR gate, read by the wizard (`conditions._visibility`), the coverage pages (`packet_answers.hidden_state`) and
the app's evaluator (golden cases). CCOF G6.0 A2 asks to attach the written drift agreements.
"""

import io

from django.test import SimpleTestCase, TestCase

from pdfminer.high_level import extract_text

from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import missing_required, visible_pages, visible_questions
from certifications.osp_modules.schema import (
    Condition,
    Module,
    ModulePage,
    Question,
    serialize_module,
    text,
    validate_module,
)
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment

G3 = MODULES_BY_KEY["g3_0_seeds"]
G6 = MODULES_BY_KEY["g6_0_production"]
SEED_ONLY = ("seed_required_characteristics", "ca_search_method", "seed_search_records")


def _shown(module, answers):
    return {q.key for _p, q in visible_questions(module, answers)}


def _pages(module, answers):
    return {p.key for p in visible_pages(module, answers)}


class OrGate(SimpleTestCase):
    def test_non_organic_stock_alone_opens_the_page_and_its_question(self):
        answers = {"seeds_used": ["organic_untreated"], "planting_stock_used": ["non_organic"]}
        self.assertIn("b_commercial_availability", _pages(G3, answers))
        shown = _shown(G3, answers)
        self.assertIn("ca_search_before_use", shown)
        self.assertFalse(set(SEED_ONLY) & shown, "the seed-only questions keep their seed gate")

    def test_non_organic_seed_opens_everything_as_before(self):
        shown = _shown(G3, {"seeds_used": ["non_organic_untreated"], "planting_stock_used": ["organic"]})
        self.assertTrue({"ca_search_before_use", *SEED_ONLY} <= shown)

    def test_only_organic_seed_and_stock_keeps_it_closed(self):
        answers = {"seeds_used": ["organic_untreated"], "planting_stock_used": ["organic"]}
        self.assertNotIn("b_commercial_availability", _pages(G3, answers))

    def test_the_gate_is_served_on_page_b_only(self):
        pages = {p["key"]: p for p in serialize_module(G3)["pages"]}
        self.assertEqual(len(pages["b_commercial_availability"]["visible_when_any"]), 2)
        self.assertNotIn("visible_when_any", pages["a_usage"])

    def test_validation_refuses_a_gate_on_a_later_question(self):
        module = Module(
            key="m",
            code="",
            title=text("M", "M"),
            nop_cites=(),
            pages=(
                ModulePage(
                    key="a",
                    title=text("A", "A"),
                    visible_when_any=(Condition("later", "truthy"),),
                    questions=(Question(key="q", kind="boolean", label=text("Q", "Q")),),
                ),
                ModulePage(
                    key="b",
                    title=text("B", "B"),
                    questions=(Question(key="later", kind="boolean", label=text("L", "L")),),
                ),
            ),
        )
        self.assertTrue(any("later" in e for e in validate_module(module, OSP_SECTION_KEYS)))


class RetiredAllOrganic(SimpleTestCase):
    def test_all_organic_is_retired_and_counts_unanswered_where_the_page_shows(self):
        question = next(q for p in G3.pages for q in p.questions if q.key == "ca_search_before_use")
        options = {o.value: o for o in question.options}
        self.assertTrue(options["all_organic"].retired)
        answers = {
            "seeds_used": ["non_organic_untreated"],
            "seedlings_used": ["none"],
            "planting_stock_used": ["none"],
            "ca_search_before_use": "all_organic",
        }
        self.assertIn("ca_search_before_use", missing_required(G3, answers))

    def test_no_documented_search_is_an_answer_with_a_review(self):
        question = next(q for p in G3.pages for q in p.questions if q.key == "ca_search_before_use")
        option = next(o for o in question.options if o.value == "no_documented_search")
        self.assertIn("§ 205.204(a)(1)", option.review)


class DriftAgreements(SimpleTestCase):
    def test_each_upload_shows_under_the_answer_that_names_it(self):
        self.assertIn("drift_agreements_upload", _shown(G6, {"drift_safeguards": ["no_spray_agreements"]}))
        self.assertNotIn("drift_agreements_upload", _shown(G6, {"drift_safeguards": ["boundary_signage"]}))
        roadside = {"borders_public_road": True, "roadside_management_steps": ["roadside_manager_agreement"]}
        self.assertIn("roadside_agreement_upload", _shown(G6, roadside))
        self.assertNotIn("roadside_agreement_upload", _shown(G6, {**roadside, "borders_public_road": False}))

    def test_routine_residue_testing_is_its_own_option(self):
        question = next(q for p in G6.pages for q in p.questions if q.key == "drift_safeguards")
        self.assertIn("routine_residue_testing", {o.value for o in question.options})


class _Plan(TestCase):
    def plan(self, module_key, answers):
        est = Establishment.objects.create(name="Batch Farm", company=Company.objects.create(name="Batch LLC"))
        return OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            module_responses={
                "schema_version": 1,
                "modules": {
                    module_key: {"answers": {k: {"at": "2026-11-08T12:00:00Z", "value": v} for k, v in answers.items()}}
                },
            },
        )


class CoveragePages(_Plan):
    """`packet_answers.hidden_state` reads the OR gate as the wizard does."""

    def row(self, osp, agent, code, ref):
        from certifications.services.certifier_register import load_forms
        from certifications.services.packet_answers import form_answer_states

        form = next(f for f in load_forms(agent) if code in (f.code, f.document_id))
        return next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == ref)

    def test_an_all_organic_plan_reads_the_not_applicable_box_as_not_applicable(self):
        osp = self.plan("g3_0_seeds", {"seeds_used": ["organic_untreated"], "planting_stock_used": ["organic"]})
        self.assertEqual(self.row(osp, "otco", "C3", "3.3 (not applicable)").state, "not_applicable")

    def test_stock_alone_holds_the_row_open_until_the_search_is_answered(self):
        osp = self.plan("g3_0_seeds", {"seeds_used": ["organic_untreated"], "planting_stock_used": ["non_organic"]})
        self.assertEqual(self.row(osp, "ccof", "ORGB47", "B1").state, "unanswered")

    def test_one_gate_unanswered_decides_nothing_yet(self):
        from certifications.services.packet_answers import hidden_state

        page = next(p for p in G3.pages if p.key == "b_commercial_availability")
        question = next(q for q in page.questions if q.key == "ca_search_before_use")
        state = hidden_state(G3, page, question, {"seeds_used": {"value": ["organic_untreated"]}})
        self.assertEqual(state[0], "unresolved")
        self.assertIn("planting_stock_used", state[1])


class OnThePage(_Plan):
    def test_no_documented_search_prints_its_review(self):
        osp = self.plan(
            "g3_0_seeds",
            {
                "seeds_used": ["organic_untreated"],
                "planting_stock_used": ["non_organic"],
                "ca_search_before_use": "no_documented_search",
            },
        )
        page = " ".join(extract_text(io.BytesIO(generate_module_pdf(osp, "g3_0_seeds"))).split())
        self.assertIn("No, no search is documented yet", page)
        self.assertIn("[REVIEW] Non-organic seed or planting stock is used with no documented search", page)


class RegisterRows(SimpleTestCase):
    def test_the_rows_are_covered(self):
        from certifications.services.certifier_register import load_forms

        for agent, code, ref in (
            ("ccof", "ORGB47", "B1"),
            ("otco", "C3", "3.3 (not applicable)"),
            ("ccof", "G6.0", "A2"),
            ("wsda", "B", "2"),
        ):
            form = next(
                f
                for f in load_forms(agent)
                if code in (f.code, f.document_id) or f.path.stem.startswith(f"2121-{code}-")
            )
            row = next(i for i in form.items if i.ref == ref)
            self.assertEqual(row.status, "covered", (agent, ref))


class PageNotPrinted(_Plan):
    """Review of back #352: the module PDF words why page B is not printed from both gates."""

    def page(self, answers):
        osp = self.plan("g3_0_seeds", answers)
        return " ".join(extract_text(io.BytesIO(generate_module_pdf(osp, "g3_0_seeds"))).split())

    def test_an_unanswered_member_of_the_or_gate_decides_nothing_yet(self):
        text = self.page({"seeds_used": ["organic_untreated"]})
        self.assertIn("Not shown until", text)
        self.assertNotIn("Does not apply to this operation.", text)

    def test_both_members_answered_word_the_gate_with_or(self):
        text = self.page({"seeds_used": ["organic_untreated"], "planting_stock_used": ["organic"]})
        self.assertIn("Does not apply: asked only when the answer to", text)
        self.assertIn(" or the answer to", text)
