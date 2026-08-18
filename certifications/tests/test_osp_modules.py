"""
Guided OSP module registry + evaluator tests (WS-2.1).

Three properties matter more than any single case and are pinned here:

  1. The registry validates clean — every citation real-shaped, both locales on every
     TextMap, every branching rule pointing backwards at a defined question. A broken
     definition must fail CI, not render as a half-blank wizard page.
  2. The condition evaluator's semantics are frozen — the frontend twin
     (src/config/osp/conditionEval.ts) asserts the same golden cases, so a semantic drift
     between the two breaks a test on whichever side changed.
  3. N/A attestation replaces the questionnaire — a module attested not-applicable
     validates complete with zero answers, because the attestation IS the answer.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import (
    CONTENT_VERSION,
    MODULE_REGISTRY,
    MODULES_BY_KEY,
    registry_errors,
    serialize_registry,
)
from certifications.osp_modules.conditions import (
    evaluate,
    invalid_choice_answers,
    missing_required,
    progress,
    validate_answer_keys,
    visible_questions,
)
from certifications.osp_modules.schema import Condition
from company.models import Company, Establishment
from users.models import User, WorksIn


class RegistryIntegrityTests(TestCase):
    def test_registry_validates_clean(self):
        errors = registry_errors()
        self.assertEqual(errors, [], "\n".join(errors))

    def test_pilot_modules_present(self):
        for key in ("g3_0_seeds", "g4_0_rotation_soil", "g8_0_record_keeping"):
            self.assertIn(key, MODULES_BY_KEY)

    def test_serialized_registry_shape(self):
        payload = serialize_registry()
        self.assertEqual(payload["content_version"], CONTENT_VERSION)
        self.assertEqual(len(payload["modules"]), len(MODULE_REGISTRY))
        g3 = next(m for m in payload["modules"] if m["key"] == "g3_0_seeds")
        self.assertEqual(g3["code"], "G3.0")
        self.assertIn("§ 205.204", g3["nop_cites"])
        # Both locales inline — the wizard picks client-side.
        self.assertTrue(g3["title"]["en"])
        self.assertTrue(g3["title"]["es"])
        first_q = g3["pages"][0]["questions"][0]
        self.assertEqual(first_q["key"], "seeds_used")
        self.assertTrue(any(o["exclusive"] for o in first_q["options"]))

    def test_g8_embeds_s11_registry_panel(self):
        g8 = MODULES_BY_KEY["g8_0_record_keeping"]
        embeds = [q.embed for page in g8.pages for q in page.questions if q.embed]
        self.assertEqual(embeds, ["s11_record_types"])


class ConditionEvaluatorTests(TestCase):
    """Golden semantics — mirrored by conditionEval.test.ts against the exported fixture."""

    def test_eq_ne(self):
        answers = {"q": {"value": "yes"}}
        self.assertTrue(evaluate(Condition("q", "eq", "yes"), answers))
        self.assertFalse(evaluate(Condition("q", "eq", "no"), answers))
        self.assertTrue(evaluate(Condition("q", "ne", "no"), answers))

    def test_includes_requires_list(self):
        self.assertTrue(evaluate(Condition("q", "includes", "a"), {"q": {"value": ["a", "b"]}}))
        self.assertFalse(evaluate(Condition("q", "includes", "a"), {"q": {"value": "a"}}))
        self.assertFalse(evaluate(Condition("q", "includes", "a"), {}))

    def test_not_includes_true_when_unanswered(self):
        # By definition an unanswered list does not include the value. This is why
        # not_includes must never be a PAGE TRIGGER (an unanswered farmer would see
        # the page) — positive triggers use includes_any, pinned below.
        self.assertTrue(evaluate(Condition("q", "not_includes", "none"), {}))
        self.assertFalse(evaluate(Condition("q", "not_includes", "none"), {"q": {"value": ["none"]}}))

    def test_includes_any_false_when_unanswered(self):
        # The positive-trigger op: conditional pages stay hidden until the trigger
        # question is actually answered with a matching value.
        cond = Condition("q", "includes_any", ("a", "b"))
        self.assertFalse(evaluate(cond, {}))
        self.assertFalse(evaluate(cond, {"q": {"value": ["c"]}}))
        self.assertTrue(evaluate(cond, {"q": {"value": ["b", "c"]}}))

    def test_truthy_falsy(self):
        self.assertTrue(evaluate(Condition("q", "truthy"), {"q": {"value": ["x"]}}))
        self.assertFalse(evaluate(Condition("q", "truthy"), {"q": {"value": []}}))
        self.assertTrue(evaluate(Condition("q", "falsy"), {"q": {"value": ""}}))
        self.assertTrue(evaluate(Condition("q", "falsy"), {}))

    def test_bare_answer_values_tolerated(self):
        self.assertTrue(evaluate(Condition("q", "eq", "yes"), {"q": "yes"}))


class G30BranchingTests(TestCase):
    """The exact branching observed on the source form, as golden cases."""

    def setUp(self):
        self.module = MODULES_BY_KEY["g3_0_seeds"]

    def _visible_page_keys(self, answers):
        return {page.key for page, _q in visible_questions(self.module, answers)}

    def test_all_none_hides_every_conditional_page(self):
        answers = {
            "seeds_used": {"value": ["none"]},
            "seedlings_used": {"value": ["none"]},
            "planting_stock_used": {"value": ["none"]},
        }
        self.assertEqual(self._visible_page_keys(answers), {"a_usage"})

    def test_unanswered_module_shows_only_page_a(self):
        # Positive triggers: nothing conditional appears before its trigger answer.
        self.assertEqual(self._visible_page_keys({}), {"a_usage"})

    def test_non_organic_seed_reveals_commercial_availability_and_gmo(self):
        answers = {"seeds_used": {"value": ["non_organic_untreated"]}}
        keys = self._visible_page_keys(answers)
        self.assertIn("b_commercial_availability", keys)
        self.assertIn("c_gmo", keys)
        self.assertNotIn("d_treatments", keys)

    def test_treated_seed_reveals_treatments_page(self):
        # Both organic-treated and non-organic-treated trigger section D.
        for value in ("organic_treated", "non_organic_treated"):
            answers = {"seeds_used": {"value": [value]}}
            self.assertIn("d_treatments", self._visible_page_keys(answers))
        # But non-organic UNtreated does not.
        answers = {"seeds_used": {"value": ["non_organic_untreated"]}}
        self.assertNotIn("d_treatments", self._visible_page_keys(answers))

    def test_planting_stock_reveals_grafting(self):
        answers = {"planting_stock_used": {"value": ["organic"]}}
        self.assertIn("e_grafting", self._visible_page_keys(answers))
        # "None used" keeps grafting hidden.
        self.assertNotIn("e_grafting", self._visible_page_keys({"planting_stock_used": {"value": ["none"]}}))

    def test_required_if_visible(self):
        # With everything "none", only page A's three questions are required.
        answers = {
            "seeds_used": {"value": ["none"]},
            "seedlings_used": {"value": ["none"]},
            "planting_stock_used": {"value": ["none"]},
        }
        self.assertEqual(missing_required(self.module, answers), [])
        # Revealing page D adds its required questions to the missing list.
        answers["seeds_used"] = {"value": ["organic_treated"]}
        missing = missing_required(self.module, answers)
        self.assertIn("treatment_verification", missing)
        self.assertIn("treatments_on_inputs_list", missing)

    def test_na_attestation_validates_empty(self):
        self.assertEqual(missing_required(self.module, {}, not_applicable=True), [])

    def test_na_refused_where_module_forbids_it(self):
        g4 = MODULES_BY_KEY["g4_0_rotation_soil"]
        # G4.0 has no N/A path — attesting it must NOT bypass validation.
        self.assertTrue(missing_required(g4, {}, not_applicable=True))

    def test_boolean_false_is_an_answer(self):
        answers = {
            "seeds_used": {"value": ["organic_treated"]},
            "seedlings_used": {"value": ["none"]},
            "planting_stock_used": {"value": ["none"]},
            "treatment_verification": {"value": ["omri_wsda"]},
            "treatments_on_inputs_list": {"value": False},
            "ca_search_before_use": {"value": "all_organic"},
            "gmo_documentation": {"value": ["all_organic"]},
        }
        self.assertEqual(missing_required(self.module, answers), [])

    def test_unknown_answer_keys_flagged(self):
        self.assertEqual(validate_answer_keys(self.module, {"bogus": 1}), ["bogus"])

    def test_invalid_choice_values_flagged(self):
        bad = invalid_choice_answers(self.module, {"seeds_used": {"value": ["glyphosate"]}})
        self.assertEqual(bad, {"seeds_used": ["glyphosate"]})

    def test_progress_counts(self):
        answers = {
            "seeds_used": {"value": ["none"]},
            "seedlings_used": {"value": ["none"]},
        }
        p = progress(self.module, answers)
        self.assertEqual(p["required"], 3)
        self.assertEqual(p["answered"], 2)
        self.assertEqual(p["missing"], ["planting_stock_used"])


class ClauseBackedQuestionTests(TestCase):
    """Questions that exist because a binding clause has nowhere else to be answered.

    Each of these was found by walking the AMS Common OSP template against the registry
    (2026-08-17) and confirming the prompt had NO home in any of the 19 modules. They are
    pinned by key here because deleting one silently re-opens the gap — the registry
    validator only checks that a definition is well-formed, never that a clause is covered.
    """

    @staticmethod
    def _keys(module_key):
        module = MODULES_BY_KEY[module_key]
        return {q.key: q for page in module.pages for q in page.questions}

    def test_crop_residue_burning_is_askable(self):
        """7 CFR 205.203(e)(3) — burning is prohibited as disposal, allowed only for two reasons."""
        q = self._keys("g5_0_pest")
        self.assertIn("burns_crop_residue", q)
        self.assertEqual(q["burns_crop_residue"].nop_cite, "§ 205.203(e)(3)")
        # The two statutory exceptions must both be offerable, and "another reason" must be
        # offerable too — an operation burning outside the exception has to be able to say so.
        reasons = {opt.value for opt in q["burn_reason"].options}
        self.assertEqual(reasons, {"disease_suppression", "seed_germination", "other"})
        # The follow-ups are gated on the yes answer, not shown to every grower.
        for key in ("burn_crops", "burn_reason"):
            self.assertEqual([(c.question, c.op) for c in q[key].visible_when], [("burns_crop_residue", "truthy")])

    def test_prohibited_material_storage_is_askable(self):
        """7 CFR 205.201(a)(5) / 205.272(a) — where prohibited substances physically sit."""
        q = self._keys("g6_0_production")
        self.assertIn("prohibited_materials_on_site", q)
        self.assertIn("prohibited_materials_storage", q)
        # NOT gated on split_operation: a wholly organic farm still keeps diesel and treated
        # lumber, and the clause applies to those the same way.
        gate = q["prohibited_materials_on_site"].visible_when
        self.assertEqual(gate, ())
        self.assertEqual(
            [(c.question, c.op) for c in q["prohibited_materials_storage"].visible_when],
            [("prohibited_materials_on_site", "truthy")],
        )
        # (a)(5) is the commingling/contact narrative — not the general practices one.
        self.assertEqual(q["prohibited_materials_storage"].compiles_to.section_key, "commingling_barriers")

    def test_packaging_composition_is_askable_and_distinct_from_reuse(self):
        """7 CFR 205.272(b)(1) composition vs (b)(2) reuse — two clauses, two questions."""
        q = self._keys("g6_1_harvest_transport")
        self.assertEqual(q["packaging_free_of_prohibited"].nop_cite, "§ 205.272(b)(1)")
        # The reuse question used to carry the (b)(1) citation, so the module cited a clause
        # it did not implement while the clause it did implement went uncited.
        self.assertEqual(q["containers_reused_from_prohibited"].nop_cite, "§ 205.272(b)(2)")
        # A supplier fact the grower may not have confirmed. Forcing a yes/no would
        # manufacture an attestation; the middle option is what keeps the answer honest.
        self.assertEqual(
            {opt.value for opt in q["packaging_free_of_prohibited"].options},
            {"confirmed", "unconfirmed", "no"},
        )
        self.assertEqual(
            [(c.question, c.op, c.value) for c in q["packaging_prohibited_detail"].visible_when],
            [("packaging_free_of_prohibited", "one_of", ["unconfirmed", "no"])],
        )

    def test_label_category_is_askable_and_shares_one_vocabulary(self):
        """7 CFR 205.301 / 205.103(b)(3) — records must identify the product BY CATEGORY.

        The per-sale column has existed since migration 0195. The plan-level question did not,
        so G7.0 cited § 205.303 in its own docstring while asking nothing about which category
        the operation actually sells under.
        """
        from history.models import ORGANIC_LABEL_CATEGORY_CHOICES

        q = self._keys("g7_0_labeling")
        self.assertIn("organic_label_categories", q)
        self.assertEqual(q["organic_label_categories"].nop_cite, "§ 205.301")
        # ONE vocabulary for one fact. A second set of values is how the OSP answer and the
        # SalesRecord column silently stop describing the same thing.
        self.assertEqual(
            [opt.value for opt in q["organic_label_categories"].options],
            [value for value, _label in ORGANIC_LABEL_CATEGORY_CHOICES],
        )

    def test_planting_stock_supplier_attestation_has_a_generated_list_behind_it(self):
        """Asking a grower to confirm a list the product cannot hold would be an empty ask.

        It is not empty: `common_osp_workbooks` generates a Supplier List from the supplier
        strings on chemical, soil, production and pest events. Pinned together so removing the
        workbook would fail the question's own justification.
        """
        from certifications.services.common_osp_workbooks import WORKBOOKS_BY_KEY

        self.assertIn("suppliers_on_supplier_list", self._keys("g3_2_planting_stock"))
        self.assertIn("supplier_list", WORKBOOKS_BY_KEY)


class ModuleDefinitionsEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Module Farm")
        self.user = User.objects.create_user(email="modules@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")
        self.client.force_authenticate(user=self.user)

    def _url(self):
        return (
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}"
            f"/osps/{self.osp.id}/module-definitions/"
        )

    def test_returns_registry_with_content_version(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["content_version"], CONTENT_VERSION)
        keys = [m["key"] for m in response.data["modules"]]
        self.assertEqual(keys, [m.key for m in MODULE_REGISTRY])

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self._url())
        self.assertIn(response.status_code, (401, 403))
