"""Irrigation water: how it is verified, what is added to it, and what goes through the system (2026-11-15).

OTCO C9 (rev. 2023/09/14) asks how irrigation water is verified free of contaminants (9.2-1a) and, for a district
that adds prohibited material, a plan naming the materials, their timing, the prevention and the district's advance
notice (9.2-1b). CCOF G6.0 (V2) asks every irrigator about prohibited additives, not only a district's (D3), with the
measures (D5), and whether materials go through the irrigation system (D6). WSDA AGR 2121 E (R 02/25) asks the same
materials, their types, and how certified crops are kept from any that are not approved (8, 8a, 8b).
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import progress, visible_questions
from certifications.services.osp_module_compiler import compile_module_contributions
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from documents.models import GeneratedDocument

MODULE = MODULES_BY_KEY["g4_2_natural_resources"]
WSDA = "Washington State Department of Agriculture (WSDA)"
CCOF = "California Certified Organic Farmers (CCOF)"
OTCO = "Oregon Tilth Certified Organic (OTCO)"
NEW_KEYS = (
    "water_verification_method",
    "water_verification_method_other",
    "water_contaminants_tested",
    "water_contaminants_tested_other",
    "district_additive_types",
    "district_additive_timing",
    "district_notifies_before_treatment",
    "non_district_water_additives",
    "water_additive_mitigation",
    "materials_via_irrigation",
    "irrigation_material_types",
    "irrigation_material_types_other",
    "irrigation_materials_all_approved",
    "irrigation_contamination_prevention",
)

#: A well-irrigated plan as filed before 2026.12.13: G4.2's required answers.
FILED = {
    "soil_water_practices": ["micro_irrigation"],
    "habitat_biodiversity_practices": ["hedgerows"],
    "conservation_plan_agency": ["none"],
    "invasive_species_practices": ["mowing"],
    "wildlife_habitat_pressure": ["neither"],
    "irrigation_source_types": ["well"],
    "irrigation_water_sources": "One well on the home block",
    "water_quality_tested": True,
    "water_quality_test_frequency": "Every spring",
    "water_from_irrigation_district": False,
    "monitoring_method": ["photo_points"],
}

WELL = {
    **FILED,
    "water_verification_method": ["lab_testing", "source_assessment"],
    "water_contaminants_tested": ["pathogens", "nitrates"],
    "non_district_water_additives": False,
    "materials_via_irrigation": True,
    "irrigation_material_types": ["fertilizers", "system_cleaners"],
    "irrigation_materials_all_approved": False,
    "irrigation_contamination_prevention": "The conventional block has its own injector and line, with a backflow valve.",
}

DISTRICT = {
    **FILED,
    "irrigation_source_types": ["irrigation_district"],
    "irrigation_source_names": "Lower Valley Irrigation District",
    "water_from_irrigation_district": True,
    "irrigation_district_additives": "yes",
    "irrigation_district_mitigation": "We close the head gate for the 48 hours after each treatment.",
    "district_additive_types": "Copper sulfate for algae",
    "district_additive_timing": "Twice in July, after our last irrigation set",
    "district_notifies_before_treatment": True,
    "water_verification_method": ["district_statement"],
}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _shown(answers) -> set:
    return {q.key for _p, q in visible_questions(MODULE, answers)}


class EveryNewQuestionIsOptional(TestCase):
    def test_a_plan_filed_before_them_stays_complete(self):
        questions = {q.key: q for page in MODULE.pages for q in page.questions}
        for key in NEW_KEYS:
            with self.subTest(question=key):
                self.assertFalse(questions[key].required)
        self.assertEqual(progress(MODULE, FILED)["missing"], [])


class TheGates(TestCase):
    def test_nothing_is_asked_of_an_operation_that_does_not_irrigate(self):
        shown = _shown({"irrigation_source_types": ["not_irrigated"], "materials_via_irrigation": True})
        for key in (
            "water_verification_method",
            "non_district_water_additives",
            "materials_via_irrigation",
            "irrigation_material_types",
        ):
            with self.subTest(question=key):
                self.assertNotIn(key, shown)

    def test_additives_are_asked_of_water_that_is_not_a_districts(self):
        self.assertIn("non_district_water_additives", _shown({"irrigation_source_types": ["well"]}))
        self.assertNotIn("non_district_water_additives", _shown({"irrigation_source_types": ["irrigation_district"]}))
        self.assertIn(
            "non_district_water_additives",
            _shown({"irrigation_source_types": ["irrigation_district", "pond_reservoir"]}),
        )

    def test_the_district_plan_opens_on_its_yes(self):
        trio = {"district_additive_types", "district_additive_timing", "district_notifies_before_treatment"}
        self.assertTrue(trio <= _shown(DISTRICT))
        self.assertFalse(trio & _shown({**DISTRICT, "irrigation_district_additives": "no_confirmed"}))

    def test_prevention_opens_only_when_not_all_materials_are_approved(self):
        self.assertIn("irrigation_contamination_prevention", _shown(WELL))
        self.assertNotIn(
            "irrigation_contamination_prevention", _shown({**WELL, "irrigation_materials_all_approved": True})
        )

    def test_what_is_tested_opens_on_laboratory_testing(self):
        self.assertIn("water_contaminants_tested", _shown(WELL))
        self.assertNotIn(
            "water_contaminants_tested", _shown({**WELL, "water_verification_method": ["source_assessment"]})
        )


class _Plan(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Creekside Orchards LLC")
        self.est = Establishment.objects.create(name="Creekside Orchards", company=company, state="WA")

    def plan(self, answers, certifier=WSDA):
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.filter(establishment=self.est).count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={
                "schema_version": 1,
                "modules": {
                    "g4_2_natural_resources": {
                        "answers": {k: {"value": v} for k, v in answers.items()},
                        "definition_version": "2026.12.13",
                    }
                },
            },
        )
        return self.osp

    def upload(self, key):
        GeneratedDocument.objects.create(
            establishment=self.est,
            folder="uploads",
            source="upload",
            title=key,
            file=SimpleUploadedFile("file.pdf", b"%PDF-1.4 file"),
            requirement=f"g4_2_natural_resources.{key}",
        )

    def row(self, agent, stem, ref):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms(agent) if f.path.stem == stem)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)


class TheModulePdfPrintsThem(_Plan):
    def test_every_answer_prints(self):
        text = _text(generate_module_pdf(self.plan(WELL), "g4_2_natural_resources"))
        for words in (
            "How do you verify that your irrigation water is free of contaminants?",
            "Laboratory testing of the water",
            "Pathogens, such as generic E. coli",
            "Irrigation line cleaners or descalers",
            "The conventional block has its own injector and line, with a backflow valve.",
        ):
            with self.subTest(words=words):
                self.assertIn(words, text)
        text = _text(generate_module_pdf(self.plan(DISTRICT), "g4_2_natural_resources"))
        for words in (
            "Copper sulfate for algae",
            "Twice in July, after our last irrigation set",
            "Does the district contact you before it adds a prohibited material?",
        ):
            with self.subTest(words=words):
                self.assertIn(words, text)

    def test_unverified_water_is_flagged(self):
        text = _text(
            generate_module_pdf(
                self.plan({**FILED, "water_verification_method": ["not_verified"]}), "g4_2_natural_resources"
            )
        )
        self.assertIn("[REVIEW] The operation states it does not verify that its irrigation water", text)

    def test_a_no_compiles_to_what_was_said(self):
        self.plan({**FILED, "non_district_water_additives": False, "materials_via_irrigation": False})
        narrative = " ".join(" ".join(v) for v in compile_module_contributions(self.osp).values())
        self.assertIn("No material is applied through the irrigation system.", narrative)
        self.assertIn(
            "No prohibited material is known to be added to irrigation water from a source other than", narrative
        )


class TheRegisterReadsThem(_Plan):
    def test_ccof_d3_asks_water_that_is_not_a_districts(self):
        self.plan(FILED, certifier=CCOF)
        self.assertTrue(self.row("ccof", "G6.0-production", "D3").is_open)
        self.plan({**FILED, "non_district_water_additives": False}, certifier=CCOF)
        self.assertEqual(self.row("ccof", "G6.0-production", "D3").state, "answered")
        # District water alone is answered by the district's own question.
        self.plan({**DISTRICT}, certifier=CCOF)
        self.assertEqual(self.row("ccof", "G6.0-production", "D3").state, "answered")

    def test_materials_through_the_system_close_ccof_d6_and_wsda_8(self):
        self.plan(WELL)
        for agent, stem, ref in (
            ("ccof", "G6.0-production", "D6"),
            ("wsda", "2121-E-biodiversity", "8"),
            ("wsda", "2121-E-biodiversity", "8a"),
            ("wsda", "2121-E-biodiversity", "8b"),
        ):
            with self.subTest(ref=ref):
                self.assertEqual(self.row(agent, stem, ref).state, "answered")

    def test_wsda_8b_needs_the_practices_when_a_material_is_not_approved(self):
        answers = {**WELL}
        del answers["irrigation_contamination_prevention"]
        self.plan(answers)
        self.assertTrue(self.row("wsda", "2121-E-biodiversity", "8b").is_open)
        self.plan({**answers, "irrigation_materials_all_approved": True})
        self.assertEqual(self.row("wsda", "2121-E-biodiversity", "8b").state, "answered")

    def test_otco_9_2_1a_reads_how_the_water_is_verified(self):
        self.plan(FILED, certifier=OTCO)
        self.assertTrue(self.row("otco", "C9-contamination-prevention", "9.2-1a").is_open)
        self.plan(WELL, certifier=OTCO)
        self.assertEqual(self.row("otco", "C9-contamination-prevention", "9.2-1a").state, "answered")

    def test_otco_9_2_1b_needs_the_plan_and_the_districts_paper(self):
        self.plan(DISTRICT, certifier=OTCO)
        self.assertEqual(self.row("otco", "C9-contamination-prevention", "9.2-1b").state, "attachment_missing")
        self.upload("irrigation_district_documentation")
        self.assertEqual(self.row("otco", "C9-contamination-prevention", "9.2-1b").state, "answered")
        # With the district's paper on file, the advance notice is the one thing a plan without it leaves open.
        answers = {**DISTRICT}
        del answers["district_notifies_before_treatment"]
        self.plan(answers, certifier=OTCO)
        state = self.row("otco", "C9-contamination-prevention", "9.2-1b")
        self.assertTrue(state.is_open)
        still_open = [part[0] for part in state.parts if part[2] not in ("answered", "not_applicable")]
        self.assertEqual(still_open, ["g4_2_natural_resources.district_notifies_before_treatment"])
