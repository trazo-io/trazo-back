"""Recordkeeping and split-operation records, as OTCO C12, CCOF G8.0 and OTCO C9 ask them (2026-11-15).

OTCO C12 (rev. 2023/12/18) asks the kinds of records kept (12.2-1), whether organic product is sourced or sold and
whether records show organic status (12.2-4, 5, 5a), the inventory system (12.2-7), and on a split operation how input
records and harvest, shipping and sales records tell organic from non-organic (12.4-1a, 1b), the last two as CCOF G8.0
C2 and C3 do. OTCO C9 asks contamination prevention through handling (9.4-3) and points the storage half of 9.4-2 at
the storage module. CCOF G6.0 A1 names three buffer-crop dispositions.
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import progress, visible_questions
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment

G8 = MODULES_BY_KEY["g8_0_record_keeping"]
G6 = MODULES_BY_KEY["g6_0_production"]
G62 = MODULES_BY_KEY["g6_2_storage"]
OTCO = "Oregon Tilth Certified Organic (OTCO)"
CCOF = "California Certified Organic Farmers (CCOF)"
NEW = (
    (
        G8,
        (
            "records_maintained_as_other",
            "sources_organic_products",
            "sells_as_organic",
            "records_identify_organic_status",
            "records_organic_status_explanation",
        ),
    ),
    (G6, ("split_input_records_distinction", "split_contamination_prevention", "split_records_distinction")),
    (G62, ("inventory_system_description", "inventory_frequency", "inventory_frequency_other")),
)

G8_ANSWERS = {
    "records_maintained_as": ["online_cloud", "hardcopy"],
    "sources_organic_products": True,
    "sells_as_organic": True,
    "records_identify_organic_status": False,
    "records_organic_status_explanation": "Our scale tickets do not say organic; the lot number on them does.",
}
SPLIT = {
    "split_operation": True,
    "split_operation_separation": "Conventional cherries are on the east block, picked by a separate crew.",
    "split_input_records_distinction": "Each spray record names the block; the conventional blocks are E1 to E3.",
    "split_contamination_prevention": "The sprayer is rinsed three times before it enters an organic block.",
    "parallel_production": False,
    "split_records_distinction": "Harvest tickets and invoices carry the block, and conventional lots start with C.",
    "harvest_transport_separation": ["different_times"],
    "buffer_strategies": ["buffer_strips", "buffer_destroyed_or_given_away"],
    "prohibited_materials_on_site": False,
}
STORAGE = {
    "inventory_system_description": "Bins are counted onto the cooler sheet by lot and counted off as they ship.",
    "inventory_frequency": "per_movement",
    "storage_shared_with_nonorganic": True,
    "storage_shared_separation": "Conventional bins sit in their own marked row, tagged red.",
}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _shown(module, answers) -> set:
    return {q.key for _p, q in visible_questions(module, answers)}


class EveryNewQuestionIsOptional(TestCase):
    def test_none_is_required(self):
        for module, keys in NEW:
            questions = {q.key: q for page in module.pages for q in page.questions}
            missing = set(progress(module, {})["missing"])
            for key in keys:
                with self.subTest(question=key):
                    self.assertFalse(questions[key].required)
                    self.assertNotIn(key, missing)


class TheOldAnswersKeepTheirMeaning(TestCase):
    def test_electronic_stays_and_the_finer_kinds_are_appended(self):
        options = [o for p in G8.pages for q in p.questions if q.key == "records_maintained_as" for o in q.options]
        self.assertEqual([o.value for o in options][:2], ["electronic", "hardcopy"])
        self.assertFalse(options[0].retired)
        self.assertEqual([o.value for o in options][2:], ["software_spreadsheet", "phone_app", "online_cloud", "other"])

    def test_buffer_options_are_appended_before_the_exclusive_one(self):
        values = [o.value for p in G6.pages for q in p.questions if q.key == "buffer_strategies" for o in q.options]
        self.assertEqual(values.index("do_not_harvest_buffer"), 11)
        self.assertLess(values.index("buffer_destroyed_or_given_away"), values.index("no_adjoining_conventional"))


class TheGates(TestCase):
    def test_split_records_follow_split_not_parallel(self):
        self.assertIn("split_records_distinction", _shown(G6, {"split_operation": True, "parallel_production": False}))
        self.assertIn("split_records_distinction", _shown(G6, {"split_operation": True}))
        self.assertNotIn(
            "split_records_distinction", _shown(G6, {"split_operation": True, "parallel_production": True})
        )
        self.assertNotIn("split_records_distinction", _shown(G6, {"split_operation": False}))

    def test_input_records_and_contamination_follow_split(self):
        for key in ("split_input_records_distinction", "split_contamination_prevention"):
            with self.subTest(question=key):
                self.assertIn(key, _shown(G6, {"split_operation": True}))
                self.assertNotIn(key, _shown(G6, {"split_operation": False}))

    def test_organic_status_follows_selling_and_its_no(self):
        self.assertNotIn("records_identify_organic_status", _shown(G8, {"sells_as_organic": False}))
        self.assertIn("records_identify_organic_status", _shown(G8, {"sells_as_organic": True}))
        self.assertNotIn(
            "records_organic_status_explanation", _shown(G8, {**G8_ANSWERS, "records_identify_organic_status": True})
        )
        self.assertIn("records_organic_status_explanation", _shown(G8, G8_ANSWERS))


class _Plan(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Hood River Orchards LLC")
        self.est = Establishment.objects.create(name="Hood River Orchards", company=company, state="OR")

    def plan(self, modules, certifier=OTCO):
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.filter(establishment=self.est).count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={
                "schema_version": 1,
                "modules": {
                    key: {"answers": {k: {"value": v} for k, v in a.items()}, "definition_version": "2026.12.15"}
                    for key, a in modules.items()
                },
            },
        )
        return self.osp

    def row(self, agent, stem, ref):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms(agent) if f.path.stem == stem)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)


class TheModulePdfsPrintThem(_Plan):
    def test_every_answer_prints(self):
        self.plan({"g8_0_record_keeping": G8_ANSWERS, "g6_0_production": SPLIT, "g6_2_storage": STORAGE})
        for module, words in (
            (
                "g8_0_record_keeping",
                (
                    "Online or cloud program",
                    "Do you source organic agricultural products",
                    "Our scale tickets do not say organic; the lot number on them does.",
                ),
            ),
            (
                "g6_0_production",
                (
                    "Each spray record names the block; the conventional blocks are E1 to E3.",
                    "The sprayer is rinsed three times before it enters an organic block.",
                    "Harvest tickets and invoices carry the block, and conventional lots start with C.",
                    "Buffer crop is destroyed or given away",
                ),
            ),
            (
                "g6_2_storage",
                (
                    "Bins are counted onto the cooler sheet by lot and counted off as they ship.",
                    "Every time product moves in or out",
                ),
            ),
        ):
            text = _text(generate_module_pdf(self.osp, module))
            for w in words:
                with self.subTest(module=module, words=w):
                    self.assertIn(w, text)


class TheRegisterReadsThem(_Plan):
    C12 = ("12.2-1", "12.2-4", "12.2-5", "12.2-5a", "12.2-7", "12.4-1a", "12.4-1b")

    def full(self, certifier=OTCO, **g8):
        return self.plan(
            {
                "g8_0_record_keeping": {**G8_ANSWERS, **g8},
                "g6_0_production": SPLIT,
                "g6_2_storage": STORAGE,
                "g7_0_labeling": {"invoices_identify_lot": True},
            },
            certifier=certifier,
        )

    def test_otco_c12_closes_with_the_answers(self):
        self.full()
        for ref in self.C12:
            with self.subTest(ref=ref):
                self.assertEqual(self.row("otco", "C12-crop-record-keeping", ref).state, "answered")

    def test_otco_c12_is_open_without_them(self):
        self.plan({"g8_0_record_keeping": {"records_maintained_as": ["electronic"]}})
        for ref in ("12.2-4", "12.2-5", "12.2-7"):
            with self.subTest(ref=ref):
                self.assertTrue(self.row("otco", "C12-crop-record-keeping", ref).is_open)

    def test_a_split_operation_that_is_not_parallel_is_asked_its_records(self):
        answers = {**SPLIT}
        del answers["split_records_distinction"]
        self.plan({"g6_0_production": answers}, certifier=CCOF)
        state = self.row("ccof", "G8.0-record-keeping", "C3")
        still_open = [p[0] for p in state.parts if p[2] not in ("answered", "not_applicable")]
        self.assertEqual(still_open, ["g6_0_production.split_records_distinction"])
        # A parallel operation answers the parallel question instead.
        self.plan(
            {
                "g6_0_production": {
                    **answers,
                    "parallel_production": True,
                    "parallel_production_distinction": "Organic lots are tagged green.",
                }
            },
            certifier=CCOF,
        )
        self.assertEqual(self.row("ccof", "G8.0-record-keeping", "C3").state, "answered")

    def test_ccof_c2_reads_the_input_records(self):
        self.plan({"g6_0_production": SPLIT}, certifier=CCOF)
        self.assertEqual(self.row("ccof", "G8.0-record-keeping", "C2").state, "answered")
        answers = {**SPLIT}
        del answers["split_input_records_distinction"]
        self.plan({"g6_0_production": answers}, certifier=CCOF)
        self.assertTrue(self.row("ccof", "G8.0-record-keeping", "C2").is_open)

    def test_otco_9_4_rows_read_contamination_and_shared_storage(self):
        self.full()
        for ref in ("9.4-2", "9.4-3"):
            with self.subTest(ref=ref):
                self.assertEqual(self.row("otco", "C9-contamination-prevention", ref).state, "answered")
        self.plan({"g6_0_production": SPLIT, "g6_2_storage": {"inventory_frequency": "weekly"}})
        state = self.row("otco", "C9-contamination-prevention", "9.4-2")
        self.assertIn(
            "g6_2_storage.storage_shared_with_nonorganic",
            [p[0] for p in state.parts if p[2] not in ("answered", "not_applicable")],
        )

    def test_ccof_a1_reads_the_buffer_dispositions(self):
        self.plan({"g6_0_production": SPLIT}, certifier=CCOF)
        self.assertEqual(self.row("ccof", "G6.0-production", "A1").state, "answered")
