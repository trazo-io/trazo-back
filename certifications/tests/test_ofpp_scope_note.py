"""OTCO OFPP item 1-3 on the G2.0 page: the module is answered in full on purpose (2026-11-16).

Oregon Tilth's Organic Fraud Prevention Plan (rev 2025/08/27, source hash re-checked 2026-11-16), 1-3:
"If you grow perennial crops or harvest wild crops, do you buy certified organic products like seeds
or planting stock?" A No lets the operation stop. G2.0 keeps the federal template, which offers no
not-applicable, so an OTCO plan's page says why it is answered in full and states the three facts
from the plan's own answers. It never concludes the plan would be not applicable.
"""

import io

from django.test import TestCase

from certifications.models import OrganicSystemPlan
from certifications.services.ofpp_scope import ofpp_scope_note, scope_facts
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment

OTCO = "Oregon Tilth Certified Organic"
WSDA = "Washington State Department of Agriculture"


def _text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class _Plan(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Hood River Cherries LLC")
        self.est = Establishment.objects.create(name="Hood River Cherries", company=company, state="OR")

    def plan(self, modules=None, certifier=OTCO, na=()):
        payload = {
            key: {"answers": {k: {"value": v} for k, v in answers.items()}} for key, answers in (modules or {}).items()
        }
        for key in na:
            payload[key] = {"answers": {}, "not_applicable": True, "na_attestation": {"by": None, "at": "2026-11-16"}}
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.filter(establishment=self.est).count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={"schema_version": 1, "modules": payload},
        )

    def facts(self, osp):
        return {fact: (state, source) for fact, state, source in scope_facts(osp)}


class TheFactsAreTheOnesThePlanStates(_Plan):
    def test_an_orchard_that_buys_organic_stock(self):
        osp = self.plan(
            {
                "g4_0_rotation_soil": {"system_type": ["perennial"]},
                "certification_contract": {"contract_scopes": ["crops"]},
                "g3_0_seeds": {"seeds_used": ["none"], "planting_stock_used": ["organic"]},
                "g3_2_planting_stock": {"stock_organic_status": "mixed"},
            }
        )
        facts = self.facts(osp)
        self.assertEqual(facts["Perennial crops grown"], ("yes", "G4.0 system type"))
        self.assertEqual(facts["Wild crops harvested"], ("no", "certification scope"))
        self.assertEqual(
            facts["Certified organic seed, seedlings or planting stock on this plan"],
            ("yes", "G3.0 and G3.2: organic planting stock, some certified organic planting stock"),
        )

    def test_nothing_answered_is_not_stated_never_no(self):
        osp = self.plan()
        self.assertEqual({state for state, _ in self.facts(osp).values()}, {"not stated"})

    def test_a_wild_harvest_and_a_wild_module_marked_not_applicable(self):
        wild = self.plan({"certification_contract": {"contract_scopes": ["crops", "wild_crops"]}})
        self.assertEqual(self.facts(wild)["Wild crops harvested"], ("yes", "certification scope"))
        none = self.plan(na=("w2_0_wild_crop",))
        self.assertEqual(self.facts(none)["Wild crops harvested"], ("no", "W2.0 marked not applicable"))

    def test_only_the_seed_module_can_say_no(self):
        """G3.2 not applying says no perennial stock went in this period, nothing about seed."""
        stock_only = self.plan(na=("g3_2_planting_stock",))
        key = "Certified organic seed, seedlings or planting stock on this plan"
        self.assertEqual(self.facts(stock_only)[key][0], "not stated")
        no_organic = self.plan({"g3_0_seeds": {"seeds_used": ["non_organic_untreated"], "seedlings_used": ["none"]}})
        self.assertEqual(self.facts(no_organic)[key], ("no", "G3.0 and G3.2"))


class TheG20PagePrintsItForOtcoOnly(_Plan):
    ANSWERS = {
        "g4_0_rotation_soil": {"system_type": ["perennial"]},
        "certification_contract": {"contract_scopes": ["crops"]},
        "g3_0_seeds": {"seedlings_used": ["purchased_organic"]},
    }

    def test_an_otco_plan_says_why_and_states_the_facts(self):
        text = _text(generate_module_pdf(self.plan(self.ANSWERS), "g2_0_fraud_prevention"))
        for words in (
            "Oregon Tilth's OFPP item 1-3",
            "This plan answers the module in full on purpose",
            "§ 205.201(a)(3)",
            "Perennial crops grown: yes (G4.0 system type).",
            "Wild crops harvested: no (certification scope).",
            "Certified organic seed, seedlings or planting stock on this plan: yes (G3.0 and G3.2: purchased "
            "organic seedlings).",
        ):
            with self.subTest(words=words):
                self.assertIn(words, text)
        # The facts, never the conclusion.
        self.assertNotIn("would be not applicable", text)

    def test_another_agents_plan_carries_no_such_note(self):
        osp = self.plan(self.ANSWERS, certifier=WSDA)
        self.assertEqual(ofpp_scope_note(osp), [])
        text = _text(generate_module_pdf(osp, "g2_0_fraud_prevention"))
        self.assertNotIn("OFPP", text)
        self.assertNotIn("Oregon Tilth", text)
