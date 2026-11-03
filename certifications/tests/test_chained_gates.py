"""A question gated on another question never outlives it: visibility is transitive (2026-11-03).

Until 2026-11-03 `visible_questions` evaluated each question's `visible_when` against the stored
answers alone and never asked whether the question it points at was itself visible. So a child gated
only on its parent's answer outlived the parent: a grower who answered `water_quality_tested = yes`
and later said "we do not irrigate" was still asked how often the water is tested (required, so the
module never completed) and the stale answer printed in the plan. Authors repeated each ancestor's
conditions on every child; a guard here froze 27 chains that had missed one.

Now a condition on a hidden question fails, in `conditions.py` and its twin `conditionEval.ts`
alike (the golden fixture carries stale-chain cases). These tests build, for every chain where a
child does not repeat an ancestor's condition, an answer set the old rule would have shown the child
for, and assert the child is hidden. The coverage page reads visibility through
`packet_answers.hidden_state`; it must agree with the evaluator on every case.
"""

from django.test import SimpleTestCase

from certifications.management.commands.export_osp_module_fixture import (
    GOLDEN_ANSWER_CASES,
    chained_gates,
    stale_answers,
)
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import evaluate, visible_questions
from certifications.services.packet_answers import hidden_state


def _chains():
    return chained_gates(MODULES_BY_KEY.values())


def _stale_answers(page, child, ancestor):
    return stale_answers(page, child, ancestor)


def _visible_keys(module, answers):
    return {q.key for _p, q in visible_questions(module, answers)}


class TransitiveVisibilityTests(SimpleTestCase):
    def test_there_are_chains_to_check(self):
        # The 27 chains frozen before this fix are among them; an empty list would pass vacuously.
        self.assertGreaterEqual(len(_chains()), 27)

    def test_a_child_is_hidden_when_an_ancestor_is_hidden_whatever_it_still_holds(self):
        unbuilt, outlived = [], []
        for module, page, child, ancestor in _chains():
            answers = _stale_answers(page, child, ancestor)
            if answers is None:
                unbuilt.append((module.key, child.key, ancestor.question))
                continue
            # The old rule, condition by condition on stored answers alone, shows the child here.
            own = tuple(page.visible_when) + tuple(child.visible_when)
            self.assertTrue(all(evaluate(c, answers) for c in own), (module.key, child.key, answers))
            if child.key in _visible_keys(module, answers):
                outlived.append((module.key, child.key, ancestor.question))
        self.assertEqual(outlived, [], "a child outlived a hidden ancestor")
        self.assertEqual(unbuilt, [], "build these answer sets by hand")

    def test_the_irrigation_chain_from_the_specimen(self):
        # The case that started it: water tested, then "not irrigated".
        module = MODULES_BY_KEY["g4_2_natural_resources"]
        visible = _visible_keys(
            module,
            {"irrigation_source_types": ["not_irrigated"], "water_quality_tested": True},
        )
        self.assertNotIn("water_quality_tested", visible)
        self.assertFalse({k for k in visible if k.startswith("water_quality_test")})


class CoveragePageAgreesTests(SimpleTestCase):
    """`hidden_state` is None exactly when the evaluator shows the question."""

    def _assert_agree(self, module, answers, label):
        visible = _visible_keys(module, answers)
        for page in module.pages:
            for q in page.questions:
                shows = hidden_state(module, page, q, answers) is None
                self.assertEqual(shows, q.key in visible, f"{label}: {module.key}.{q.key}")

    def test_on_every_golden_case(self):
        for module_key, cases in GOLDEN_ANSWER_CASES.items():
            for name, answers in cases.items():
                self._assert_agree(MODULES_BY_KEY[module_key], answers, name)

    def test_on_every_stale_chain(self):
        for module, page, child, ancestor in _chains():
            answers = _stale_answers(page, child, ancestor)
            if answers is not None:
                self._assert_agree(module, answers, f"stale {child.key}")
