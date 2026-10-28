"""A panel, table or notice never holds a register row open (e2e packet run, 2026-10-28).

An `info` question is shown to the operator and has no answer of its own, so it reads `not_assessed`
always. A row that cited one beside real questions folded to that state whatever the grower
answered: WSDA J13 stayed "not checked against this plan's answers" with every question answered,
and 33 other rows across WSDA, CCOF and OTCO the same. A row that cites ONLY panels still reads
`not_assessed`: nothing there was answered.

The question index named a hidden part only by the answer that hides it, so WSDA J1 printed
"Answered at ..." and then "does not apply (... answered Our own crew)" under one item. Each such
line now names the question that does not apply.
"""

from django.test import SimpleTestCase, TestCase

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.services.certifier_register import load_forms, load_unmapped
from certifications.services.packet_answers import RowState, _Answers, row_answer_state
from certifications.services.packet_index_recorder import Recorder
from certifications.services.question_index import index_row
from company.models import Company, Establishment

G61 = "g6_1_harvest_transport"


def _item(agent, label_or_code, ref):
    form = next(f for f in load_forms(agent) if label_or_code in (f.code, f.label))
    return next(i for i in form.items if i.ref == ref)


class InfoQuestionsInRowsTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Wenatchee Orchards")
        est = Establishment.objects.create(name="Wenatchee Orchard", company=company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(establishment=est, version_number=1, status="draft")

    def answer(self, module, **values):
        self.osp.module_responses = {"modules": {module: {"answers": values}}}
        self.osp.save(update_fields=["module_responses"])

    def state(self, agent, form, ref):
        self.osp.refresh_from_db()
        return row_answer_state(_Answers(self.osp), _item(agent, form, ref))

    def test_wsda_j13_closes_on_its_questions_with_the_handler_table_shown(self):
        self.answer(G61, first_stop_before_buyer=["hydrocooler"], handled_by_another_operation="yes_certified")
        state = self.state("wsda", "J", "13")
        # J13 is `partial` in the register (AGR 2519 is not generated), so answered reads partial.
        self.assertEqual(state.state, "partial")
        self.assertNotIn("off_farm_handler_table", {part[0].split(".")[1] for part in state.parts})

    def test_an_unanswered_question_beside_a_panel_still_holds_the_row_open(self):
        self.answer(G61, handled_by_another_operation="yes_certified")
        self.assertEqual(self.state("wsda", "J", "13").state, "unanswered")

    def test_a_row_citing_only_a_panel_is_still_not_assessed(self):
        self.assertEqual(self.state("wsda", "Input Material List", "Table (input name)").state, "not_assessed")


class CcofA1CitesNoNoticeTests(SimpleTestCase):
    def test_the_unlabeled_bulk_notice_is_unmapped_not_cited(self):
        """CCOF G7.0 A1 cited the write-time notice (back #241), so the row could never close."""
        key = "g7_0_labeling.unlabeled_bulk_notice"
        self.assertNotIn(key, _item("ccof", "G7.0", "A1").questions)
        self.assertIn(key, load_unmapped("ccof"))

    def test_no_row_cites_a_notice(self):
        """A panel (an info question with an embed) shows records beside the answer; a notice with no
        embed only explains an answer, so a row cites the answer instead."""
        notices = {
            f"{m.key}.{q.key}"
            for m in MODULES_BY_KEY.values()
            for p in m.pages
            for q in p.questions
            if q.kind == "info" and not q.embed
        }
        self.assertIn("g7_0_labeling.unlabeled_bulk_notice", notices)
        for agent in ("wsda", "ccof", "otco"):
            for form in load_forms(agent):
                for item in form.items:
                    with self.subTest(agent=agent, form=form.label, ref=item.ref):
                        self.assertFalse(notices & set(item.questions))


class QuestionIndexNamesTheHiddenQuestionTests(SimpleTestCase):
    def _label(self, key):
        return next(q.label["en"] for p in MODULES_BY_KEY[G61].pages for q in p.questions if q.key == key)

    def test_a_part_that_does_not_apply_names_its_question(self):
        state = RowState(
            "1",
            "answered",
            parts=(
                (f"{G61}.who_harvests", "", "answered", ""),
                (f"{G61}.custom_harvester_records", "", "not_applicable", "who_harvests = ['own_crew']"),
            ),
        )
        row = index_row(state, None, Recorder(), None, {})
        (part,) = row.open_parts
        self.assertEqual(part.subjects, (self._label("custom_harvester_records"),))
        self.assertIn("answered Our own crew", part.detail)

    def test_two_questions_hidden_by_one_answer_print_one_line_naming_both(self):
        detail = "who_harvests = ['own_crew']"
        state = RowState(
            "1",
            "not_applicable",
            parts=(
                (f"{G61}.custom_harvester_records", "", "not_applicable", detail),
                (f"{G61}.custom_harvester_instructions", "", "not_applicable", detail),
            ),
        )
        (part,) = index_row(state, None, Recorder(), None, {}).open_parts
        self.assertEqual(
            part.subjects,
            (self._label("custom_harvester_records"), self._label("custom_harvester_instructions")),
        )
