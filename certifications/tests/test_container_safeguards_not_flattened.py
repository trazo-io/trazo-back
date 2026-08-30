"""One boolean must not speak for three safeguards across every container type.

WHY THIS EXISTS
---------------
The last register blocker (CCOF G6.1 B1, WSDA J 5). G6.1 §B asked a single boolean — "are these
containers new, dedicated to organic use, OR cleaned before each use?" — answered once for every
container type the operation had ticked, and compiled it as an affirmative covering all three
predicates. On the pilot, `container_types` was "Reusable lugs; Single-use cartons; Totes" and one
"Yes" spoke for all of them while the cleaning description substantiated only the lugs. The plan
asserted more than the operator had said, which is what made it a P0 rather than a gap.

WSDA J5 asks exactly this as a four-way checkbox — cleaned prior / lined prior / only new /
dedicated to organic — and a bulk-trailer safeguard need not match a picking-bag safeguard.

WHY THE OLD ANSWER WAS DELETED, NOT MAPPED. A stored `True` does not say WHICH safeguard applied;
that missing information IS the defect. Migration 0036 clears it, so those plans read as
unanswered and `_module_status` reports them in progress. Mapping `True` to a guessed safeguard
would put a claim in front of a certifier that nobody made.
"""

from django.test import TestCase

from certifications.osp_modules import MODULE_REGISTRY
from certifications.osp_modules.conditions import visible_questions


def _module():
    return next(m for m in MODULE_REGISTRY if m.key == "g6_1_harvest_transport")


def _questions():
    return {q.key: q for page in _module().pages for q in page.questions}


class ContainerSafeguardsTests(TestCase):
    def test_the_flattened_boolean_is_gone(self):
        self.assertNotIn("containers_clean_or_dedicated", _questions())

    def test_the_operator_says_which_safeguard_applies(self):
        question = _questions().get("container_safeguards")
        self.assertIsNotNone(question)
        self.assertEqual(question.kind, "checkbox_group")
        self.assertEqual(
            {o.value for o in question.options},
            {"cleaned_prior", "lined_prior", "only_new", "organic_only"},
            "WSDA J5's four safeguards, each answerable on its own",
        )

    def test_nothing_compiles_a_combined_or_claim(self):
        # The exact sentence the defect consisted of: one assertion covering three predicates.
        for question in _questions().values():
            rule = question.compiles_to
            if rule is None:
                continue
            template = rule.template.lower()
            self.assertNotIn(
                "new, dedicated to organic use, or cleaned",
                template,
                f"{question.key} still compiles a combined claim",
            )

    def test_the_cleaning_description_follows_the_safeguard_that_needs_it(self):
        # It used to be gated on the boolean being truthy, so it appeared for "only new
        # containers" — where there is no cleaning to describe — and was required to explain a
        # safeguard the operator had not claimed.
        answers = {"container_safeguards": {"value": ["only_new"]}}
        visible = {q.key for _page, q in visible_questions(_module(), answers)}
        self.assertNotIn("containers_cleaning_method", visible)

        answers = {"container_safeguards": {"value": ["cleaned_prior"]}}
        visible = {q.key for _page, q in visible_questions(_module(), answers)}
        self.assertIn("containers_cleaning_method", visible)

    def test_lining_also_opens_the_description(self):
        # WSDA lists lining as its own safeguard, and "what did you line them with" is the same
        # question as "how did you clean them" from a reviewer's side.
        answers = {"container_safeguards": {"value": ["lined_prior"]}}
        visible = {q.key for _page, q in visible_questions(_module(), answers)}
        self.assertIn("containers_cleaning_method", visible)

    def test_no_stored_answer_survives_under_the_retired_key(self):
        # Anti-vacuity for migration 0036: if the key were still populated anywhere, the module
        # would keep compiling the old combined claim from stored data even with the question
        # removed from the registry.
        from certifications.models import OrganicSystemPlan

        for osp in OrganicSystemPlan.objects.all():
            module = ((osp.module_responses or {}).get("modules") or {}).get("g6_1_harvest_transport") or {}
            self.assertNotIn("containers_clean_or_dedicated", module.get("answers") or {})
