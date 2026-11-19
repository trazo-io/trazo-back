"""CCOF G8.0 D1, the supply-chain scenarios, stated on G8.0 §D from the plan's own answers (content 2026.12.22).

D1 asks the operation to mark each scenario that applies: organic seed, seedlings or planting stock bought in; organic
product sourced for resale; crops sent to another operation for storage, handling or processing; packing under another
operation's label. Each is answered where CCOF sends it (G3.0 and G3.0b, G6.5, G6.1 and G6.2, G7.0), so G8.0 §D states it
from those answers and never asks it again. A section not answered yet is "not stated", never "no".
"""

import io

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.sourcing_scenarios import sourcing_scenario_lines, sourcing_scenarios
from company.models import Company, Establishment
from users.models import User, WorksIn

CCOF = "CCOF Certification Services, LLC"

SEED = "Buys certified organic seed, annual seedlings or planting stock"
RESALE = "Sources certified organic crops or products for resale or distribution"
HANDLED = "Sends certified organic crops to another operation for storage, handling or processing"
BRAND = "Packs into brands or labels owned by other operations"

#: Every section answered, and no scenario applies.
NONE_APPLY = {
    "g3_0_seeds": {"seeds_used": ["none"], "seedlings_used": ["none"], "planting_stock_used": ["established_in_place"]},
    "g6_5_sales_soe": {"sales_soe_supplier_verification": "no"},
    "g6_1_harvest_transport": {"handled_by_another_operation": "no"},
    "g6_2_storage": {"storage_locations": ["on_farm_cold"]},
    "g7_0_labeling": {"product_leaves_as": ["bulk_bins_marked"]},
}


def _text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class _Plan(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Kings River Orchards LLC")
        self.est = Establishment.objects.create(name="Kings River Orchards", company=self.company, state="CA")

    def plan(self, modules=None, na=(), **changes):
        merged = {key: dict(answers) for key, answers in (modules if modules is not None else NONE_APPLY).items()}
        for key, answers in changes.items():
            merged.setdefault(key, {}).update(answers)
        payload = {key: {"answers": {k: {"value": v} for k, v in answers.items()}} for key, answers in merged.items()}
        for key in na:
            payload[key] = {
                "answers": payload.get(key, {}).get("answers", {}),
                "not_applicable": True,
                "na_attestation": {"by": None, "at": "2026-11-19"},
            }
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.filter(establishment=self.est).count() + 1,
            status="draft",
            certifier_name=CCOF,
            module_responses={"schema_version": 1, "modules": payload},
        )

    def states(self, osp):
        return {s.label["en"]: (s.state, s.basis) for s in sourcing_scenarios(osp)}


class EachScenarioIsTheAnswerGivenWhereItIsAsked(_Plan):
    def test_nothing_applies_and_the_page_says_so(self):
        osp = self.plan()
        self.assertEqual(
            {k: v[0] for k, v in self.states(osp).items()}, dict.fromkeys((SEED, RESALE, HANDLED, BRAND), "no")
        )
        lines, reviews = sourcing_scenario_lines(osp)
        self.assertEqual(lines[-1], "None of these applies, as the plan states it.")
        self.assertEqual(reviews, [])

    def test_nothing_answered_is_not_stated_never_no(self):
        osp = self.plan({})
        for label, (state, basis) in self.states(osp).items():
            self.assertEqual(state, "not stated", label)
            self.assertTrue(basis, label)
        lines, _ = sourcing_scenario_lines(osp)
        self.assertNotIn("None of these applies, as the plan states it.", lines)
        self.assertIn(f"{RESALE}: not stated (G6.5 not answered yet).", lines)
        self.assertIn(f"{BRAND}: not stated (G7.0 not answered yet).", lines)

    def test_seedlings_bought_certified_organic(self):
        osp = self.plan(g3_0_seeds={"seedlings_used": ["purchased_organic"]})
        self.assertEqual(self.states(osp)[SEED], ("yes", ("G3.0: purchased organic seedlings",)))

    def test_organic_seed_with_no_source_is_not_stated(self):
        osp = self.plan(g3_0_seeds={"seeds_used": ["organic_untreated"]})
        self.assertEqual(self.states(osp)[SEED], ("not stated", ("G3.0: organic seed, its source not stated",)))

    def test_seed_saved_on_the_farm_is_not_bought(self):
        osp = self.plan(g3_0_seeds={"seeds_used": ["organic_untreated"], "seed_source": ["save_own"]})
        self.assertEqual(self.states(osp)[SEED], ("no", ("G3.0: none bought in",)))

    def test_stock_from_a_nursery_is_named_under_g30b(self):
        osp = self.plan(
            g3_0_seeds={"planting_stock_used": ["organic"]},
            g3_2_planting_stock={"stock_source": ["nursery"]},
        )
        scenario = next(x for x in sourcing_scenarios(osp) if x.key == "organic_seed_or_stock")
        self.assertEqual(
            (scenario.state, scenario.basis, scenario.decided_by),
            ("yes", ("G3.0b: organic planting stock from a nursery",), ("G3.0b",)),
        )

    def test_handled_by_a_certified_operation_is_decided_by_g61_alone(self):
        modules = {k: v for k, v in NONE_APPLY.items() if k != "g6_2_storage"}
        osp = self.plan(modules, g6_1_harvest_transport={"handled_by_another_operation": "yes_certified"})
        scenario = next(x for x in sourcing_scenarios(osp) if x.key == "crop_to_another_operation")
        self.assertEqual((scenario.state, scenario.decided_by), ("yes", ("G6.1",)))

    def test_product_bought_in_for_resale(self):
        osp = self.plan(g6_5_sales_soe={"sales_soe_supplier_verification": "yes"})
        self.assertEqual(self.states(osp)[RESALE], ("yes", ("G6.5: buys in or co-markets organic product",)))

    def test_handled_off_the_farm_by_a_certified_operation(self):
        osp = self.plan(g6_1_harvest_transport={"handled_by_another_operation": "yes_certified"})
        self.assertEqual(
            self.states(osp)[HANDLED], ("yes", ("G6.1: handled off the farm by a certified organic operation",))
        )

    def test_handling_after_ownership_passes_is_not_this_scenario(self):
        """CCOF G6.1 C1 ends the handling form at this answer: the crop is that operation's once delivered."""
        osp = self.plan(g6_1_harvest_transport={"handled_by_another_operation": "yes_ownership_transfers"})
        state, basis = self.states(osp)[HANDLED]
        self.assertEqual(state, "no")
        self.assertIn("G6.1: handled by another operation only after ownership passes to it", basis)

    def test_storage_off_the_farm_while_still_owned(self):
        osp = self.plan(g6_2_storage={"storage_locations": ["commercial_cold_off_farm"], "owns_crop_in_storage": "yes"})
        self.assertEqual(
            self.states(osp)[HANDLED], ("yes", ("G6.2: stored off the farm while the operation still owns it",))
        )

    def test_storage_contracted_out_with_ownership_unanswered(self):
        osp = self.plan(
            g6_2_storage={"storage_locations": ["certified_handler"], "third_party_storage_contracted": True}
        )
        self.assertEqual(self.states(osp)[HANDLED][0], "yes")

    def test_storage_off_the_farm_with_ownership_unstated_is_not_stated(self):
        osp = self.plan(g6_2_storage={"storage_locations": ["uncertified_facility"]})
        state, basis = self.states(osp)[HANDLED]
        self.assertEqual(state, "not stated")
        self.assertIn("G6.2: stored off the farm, whether the operation still owns it there not stated", basis)

    def test_storage_off_the_farm_after_ownership_passes(self):
        osp = self.plan(g6_2_storage={"storage_locations": ["commercial_cold_off_farm"], "owns_crop_in_storage": "no"})
        self.assertEqual(self.states(osp)[HANDLED][0], "no")

    def test_handling_answered_but_storage_not_is_not_stated_and_says_which(self):
        modules = {k: v for k, v in NONE_APPLY.items() if k != "g6_2_storage"}
        state, basis = self.states(self.plan(modules))[HANDLED]
        self.assertEqual(state, "not stated")
        self.assertEqual(basis, ("G6.1: nobody off the operation handles the crop", "G6.2 not answered yet"))

    def test_storage_marked_not_applicable_closes_it(self):
        modules = {k: v for k, v in NONE_APPLY.items() if k != "g6_2_storage"}
        self.assertEqual(self.states(self.plan(modules, na=("g6_2_storage",)))[HANDLED][0], "no")

    def test_packed_under_the_buyers_label(self):
        osp = self.plan(g7_0_labeling={"product_leaves_as": ["bulk_bins_marked", "buyer_label"]})
        self.assertEqual(
            self.states(osp)[BRAND], ("yes", ("G7.0: sold under the buyer's own label (private label or repack)",))
        )

    def test_storage_somewhere_else_described_in_words_is_not_stated(self):
        """An "Other" place says nothing Trazo can read about who stores the crop (review of back #506)."""
        osp = self.plan(
            g6_2_storage={"storage_locations": ["on_farm_cold", "other"], "storage_other_description": "Packer CA room"}
        )
        state, basis = self.states(osp)[HANDLED]
        self.assertEqual(state, "not stated")
        self.assertIn(
            'G6.2: stored at another place ("Packer CA room"), whether another operation stores it not stated', basis
        )
        self.assertNotIn("G6.2: stored on the farm only", basis)

    def test_ownership_passing_beside_a_storage_contract_is_not_stated(self):
        """The two G6.2 answers cannot both hold, so neither decides it (review of back #506)."""
        osp = self.plan(
            g6_2_storage={
                "storage_locations": ["certified_handler"],
                "owns_crop_in_storage": "no",
                "third_party_storage_contracted": True,
            }
        )
        state, basis = self.states(osp)[HANDLED]
        self.assertEqual(state, "not stated")
        self.assertTrue(any("the two answers disagree" in b for b in basis), basis)

    def test_a_product_form_described_in_words_is_not_stated(self):
        """An "Other" form may be another company's label; Trazo does not read the words (review of back #506)."""
        osp = self.plan(
            g7_0_labeling={"product_leaves_as": ["bulk_bins_marked", "other"], "product_leaves_as_other": "Co-packed"}
        )
        self.assertEqual(
            self.states(osp)[BRAND],
            (
                "not stated",
                ('G7.0: leaves in another form ("Co-packed"), whether under another company\'s label not stated',),
            ),
        )

    def test_labeling_marked_not_applicable_is_no(self):
        modules = {k: v for k, v in NONE_APPLY.items() if k != "g7_0_labeling"}
        self.assertEqual(
            self.states(self.plan(modules, na=("g7_0_labeling",)))[BRAND], ("no", ("G7.0 marked not applicable",))
        )


class SectionBMustAgreeWithTheScenarios(_Plan):
    def test_sources_nothing_beside_seedlings_bought_organic(self):
        osp = self.plan(
            g3_0_seeds={"seedlings_used": ["purchased_organic"]},
            g8_0_record_keeping={"sources_organic_products": False},
        )
        _, reviews = sourcing_scenario_lines(osp)
        self.assertEqual(
            reviews,
            [
                "[REVIEW] §B says the operation sources no organic agricultural products, but the plan states it buys "
                "certified organic seed, annual seedlings or planting stock (G3.0 and G3.0b)."
            ],
        )

    def test_sources_some_while_nothing_is_bought_in(self):
        osp = self.plan(g8_0_record_keeping={"sources_organic_products": True})
        _, reviews = sourcing_scenario_lines(osp)
        self.assertEqual(len(reviews), 1)
        self.assertIn("G3.0, G3.0b and G6.5 name none bought in", reviews[0])

    def test_agreeing_answers_raise_nothing(self):
        osp = self.plan(
            g6_5_sales_soe={"sales_soe_supplier_verification": "yes"},
            g8_0_record_keeping={"sources_organic_products": True},
        )
        self.assertEqual(sourcing_scenario_lines(osp)[1], [])


class TheModulePdfPrintsPageD(_Plan):
    def test_the_four_lines_print_under_their_heading(self):
        osp = self.plan(
            g6_1_harvest_transport={"handled_by_another_operation": "yes_certified"},
            g8_0_record_keeping={"sources_organic_products": True},
        )
        text = _text(generate_module_pdf(osp, "g8_0_record_keeping"))
        heading = "D. Organic products bought in, and other operations"
        self.assertIn(heading, text)
        page_d = text[text.index(heading) :]
        self.assertIn("What this plan says about organic products you buy in", page_d)
        self.assertIn(f"{SEED}: no (G3.0: none bought in).", page_d)
        self.assertIn(f"{RESALE}: no (G6.5: sells only what it grows).", page_d)
        self.assertIn(f"{HANDLED}: yes (G6.1: handled off the farm by a certified organic operation).", page_d)
        self.assertIn(f"{BRAND}: no (G7.0: no product leaves under another company's label).", page_d)
        self.assertIn("[REVIEW] §B says the operation sources organic agricultural products", page_d)


class TheCoverageRowReadsTheScenarios(_Plan):
    def _d1_state(self, osp):
        from certifications.services.certifier_register import load_forms
        from certifications.services.packet_answers import _Answers, row_answer_state

        form = next(f for f in load_forms("ccof") if f.code == "G8.0")
        item = next(i for i in form.items if i.ref == "D1")
        return row_answer_state(_Answers(osp), item, form.document_id)

    def test_answered_once_every_scenario_is_decided(self):
        # Organic seed is not used, so the optional seed source decides nothing and stays blank.
        osp = self.plan(g3_0_seeds={"seeds_used": ["non_organic_untreated"]})
        self.assertEqual(self._d1_state(osp).state, "answered")

    def test_unconfirmed_while_section_b_disagrees(self):
        osp = self.plan(
            g3_0_seeds={"seedlings_used": ["purchased_organic"]},
            g8_0_record_keeping={"sources_organic_products": False},
        )
        state = self._d1_state(osp)
        self.assertEqual(state.state, "unconfirmed")
        self.assertTrue(state.detail.startswith("§B says the operation sources no organic agricultural products"))

    def test_open_while_one_is_not_stated_naming_it(self):
        modules = {k: v for k, v in NONE_APPLY.items() if k != "g7_0_labeling"}
        state = self._d1_state(self.plan(modules))
        self.assertEqual(state.state, "unanswered")
        self.assertEqual(state.detail, f"{BRAND}: not stated (G7.0 not answered yet)")


class TheWizardPanelReadsTheSameRows(_Plan):
    def test_endpoint(self):
        user = User.objects.create_user(email="d1@test.com", password="x", first_name="Ana")
        WorksIn.objects.create(user=user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        client = APIClient()
        client.force_authenticate(user=user)
        modules = {k: v for k, v in NONE_APPLY.items() if k != "g7_0_labeling"}
        osp = self.plan(modules, g6_5_sales_soe={"sales_soe_supplier_verification": "yes"})
        response = client.get(
            f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{osp.id}/sourcing-scenarios/"
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["scenarios"]
        # Each yes or no names only the modules that decided it (review of app #440).
        self.assertEqual([r["decided_by"] for r in rows], [["G3.0"], ["G6.5"], ["G6.1", "G6.2"], []])
        self.assertEqual(
            [(r["key"], r["state"], r["answered_in"], r["unanswered_in"]) for r in rows],
            [
                ("organic_seed_or_stock", "no", ["G3.0", "G3.0b"], []),
                ("organic_product_for_resale", "yes", ["G6.5"], []),
                ("crop_to_another_operation", "no", ["G6.1", "G6.2"], []),
                ("packs_for_brand_owners", "not_stated", ["G7.0"], ["G7.0"]),
            ],
        )
        self.assertIsNone(response.json()["section_b"])
        self.assertEqual(
            rows[1]["label"]["es"], "Adquiere cultivos o productos orgánicos certificados para revender o distribuir"
        )

    def test_endpoint_names_the_module_still_open_and_the_section_b_disagreement(self):
        user = User.objects.create_user(email="d1b@test.com", password="x", first_name="Ana")
        WorksIn.objects.create(user=user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        client = APIClient()
        client.force_authenticate(user=user)
        modules = {k: v for k, v in NONE_APPLY.items() if k != "g6_2_storage"}
        osp = self.plan(
            modules,
            g3_0_seeds={"seedlings_used": ["purchased_organic"]},
            g8_0_record_keeping={"sources_organic_products": False},
        )
        body = client.get(
            f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{osp.id}/sourcing-scenarios/"
        ).json()
        handled = next(r for r in body["scenarios"] if r["key"] == "crop_to_another_operation")
        self.assertEqual((handled["state"], handled["unanswered_in"]), ("not_stated", ["G6.2"]))
        seed = next(r for r in body["scenarios"] if r["key"] == "organic_seed_or_stock")
        self.assertEqual((seed["state"], seed["decided_by"]), ("yes", ["G3.0"]))
        self.assertEqual(body["section_b"], "says_none")
