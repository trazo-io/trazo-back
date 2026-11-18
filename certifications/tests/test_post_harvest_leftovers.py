"""Post-harvest, storage and harvest leftovers across CCOF G6.4 and WSDA AGR 2121 J, K, L (content 2026.12.20).

G6.4 asks how cleaning differs before non-certified crops on shared equipment (L 6a), how the chlorine rinse is checked
(L 15a), how cleaning and purge records link to production records (L 7), takes the purge procedures (L 4) and the
operator's own product list (CCOF G6.4 A2), and prints where facility pest materials (G9.0) and packaging (G6.1) are
answered, with G6.1's answer (CCOF G6.4 A4, C1). G6.1 asks the documentation behind unstamped containers (J 7b); each
of the three modules has an optional notes field (J 14, K 4, L 18). Every new question is optional.
"""

import io
from pathlib import Path

from django.test import SimpleTestCase, TestCase

import yaml

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import missing_required, visible_questions
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment

G61 = MODULES_BY_KEY["g6_1_harvest_transport"]
G62 = MODULES_BY_KEY["g6_2_storage"]
G64 = MODULES_BY_KEY["g6_4_handling"]
NEW = {
    "g6_4_handling": {
        "products_list_upload",
        "purge_procedure_upload",
        "chlorine_rinse_monitoring",
        "cleaning_differs_by_status",
        "handling_records_linkage",
        "handling_additional_notes",
    },
    "g6_1_harvest_transport": {"container_safeguard_documentation", "harvest_additional_notes"},
    "g6_2_storage": {"storage_additional_notes"},
}
HANDLING = {"handling_activities": ["washing", "packing"]}


def _visible(module, answers) -> set:
    return {q.key for _page, q in visible_questions(module, answers)}


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class TheQuestionsOpenWhereTheFormsAskThem(SimpleTestCase):
    def test_cleaning_differences_are_asked_only_of_shared_equipment(self):
        self.assertNotIn(
            "cleaning_differs_by_status", _visible(G64, {**HANDLING, "shares_handling_area_or_equipment": False})
        )
        shared = {**HANDLING, "shares_handling_area_or_equipment": True, "cleaning_differs_by_status": "differs"}
        self.assertIn("cleaning_differences_detail", _visible(G64, shared))
        same = {**shared, "cleaning_differs_by_status": "same"}
        self.assertNotIn("cleaning_differences_detail", _visible(G64, same))

    def test_the_purge_upload_and_the_rinse_check_follow_their_answers(self):
        self.assertIn(
            "purge_procedure_upload", _visible(G64, {**HANDLING, "food_contact_cleaning_methods": ["purging"]})
        )
        self.assertNotIn(
            "purge_procedure_upload", _visible(G64, {**HANDLING, "food_contact_cleaning_methods": ["sweeping"]})
        )
        rinse = {**HANDLING, "uses_water": True, "wash_water_additives_added": True, "wash_water_chlorine_added": True}
        self.assertIn(
            "chlorine_rinse_monitoring",
            _visible(G64, {**rinse, "wash_water_chlorine_final_rinse": "chlorine_at_or_below_sdwa"}),
        )
        self.assertNotIn(
            "chlorine_rinse_monitoring", _visible(G64, {**rinse, "wash_water_chlorine_final_rinse": "water_only_rinse"})
        )

    def test_container_documentation_is_asked_only_where_containers_are_not_all_stamped(self):
        self.assertIn(
            "container_safeguard_documentation", _visible(G61, {"harvest_containers_stamped_organic": "some"})
        )
        self.assertNotIn(
            "container_safeguard_documentation", _visible(G61, {"harvest_containers_stamped_organic": "all"})
        )

    def test_no_new_question_reopens_a_finished_plan(self):
        for module, answers in (
            (
                G64,
                {**HANDLING, "shares_handling_area_or_equipment": True, "food_contact_cleaning_methods": ["purging"]},
            ),
            (G61, {"harvest_containers_stamped_organic": "none"}),
            (G62, {}),
        ):
            self.assertEqual(set(missing_required(module, answers)) & NEW[module.key], set(), module.key)

    def test_the_product_list_upload_is_a_supplement_never_a_substitute(self):
        upload = next(q for page in G64.pages for q in page.questions if q.key == "products_list_upload")
        self.assertTrue(upload.label["en"].startswith("You can also attach"), upload.label["en"])


class TheGoldenCasesReachTheirGates(SimpleTestCase):
    """Review of #482 / #430: three golden cases set no `handling_activities`, so G6.4's gated pages stayed hidden
    and the cases exported the same visible set as an empty answer, testing none of the new gates."""

    def test_each_new_case_shows_the_question_it_is_named_for(self):
        from certifications.management.commands.export_osp_module_fixture import GOLDEN_ANSWER_CASES

        cases = GOLDEN_ANSWER_CASES
        for module, case, target in (
            (G64, "shared_and_differs", "cleaning_differences_detail"),
            (G64, "purging", "purge_procedure_upload"),
            (G64, "chlorine_rinse_checked", "chlorine_rinse_monitoring"),
            (G61, "some_unstamped", "container_safeguard_documentation"),
        ):
            self.assertIn(target, _visible(module, cases[module.key][case]), case)


class TheHandlingPdfSaysWhereTheOtherAnswersAre(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Medford Pack LLC")
        self.est = Establishment.objects.create(name="Medford Pack", company=company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def _store(self, modules):
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {
                key: {"answers": {k: {"at": "2026-11-18T10:00:00Z", "value": v} for k, v in answers.items()}}
                for key, answers in modules.items()
            },
        }
        self.osp.save(update_fields=["module_responses"])

    def test_the_packaging_line_prints_g6_1s_own_answer_and_the_pest_line_names_g9_0(self):
        self._store(
            {
                "g6_4_handling": {**HANDLING, "handling_records_linkage": "Run logs carry the lot code."},
                "g6_1_harvest_transport": {"packaging_free_of_prohibited": "confirmed"},
            }
        )
        text = _pdf_text(generate_module_pdf(self.osp, "g6_4_handling"))
        self.assertIn("Whether all packaging is free of prohibited substances is asked in G6.1", text)
        self.assertIn("G6.1 answers:", text)
        self.assertIn("Facility pest management", text)
        self.assertIn("G9.0", text)
        self.assertIn("Run logs carry the lot code.", text)

    def test_an_unanswered_g6_1_prints_no_answer_for_it(self):
        self._store({"g6_4_handling": HANDLING})
        text = _pdf_text(generate_module_pdf(self.osp, "g6_4_handling"))
        self.assertIn("Whether all packaging is free of prohibited substances is asked in G6.1", text)
        self.assertNotIn("G6.1 answers:", text)


class TheRegisterRowsAreClosed(SimpleTestCase):
    ROWS = {
        "ccof/forms/G6.4-onfarm-postharvest.yaml": ("A2", "A4", "C1"),
        "wsda/forms/2121-L-post-harvest.yaml": ("4", "6a", "7", "15a", "18"),
        "wsda/forms/2121-J-harvest.yaml": ("7b", "14"),
        "wsda/forms/2121-K-storage.yaml": ("4",),
    }

    def test_every_row_is_covered_and_cites_questions_that_exist(self):
        root = Path(__file__).resolve().parents[2] / "documentation/compliance/certifiers"
        keys = {f"{m.key}.{q.key}" for m in MODULES_BY_KEY.values() for page in m.pages for q in page.questions}
        for path, refs in self.ROWS.items():
            items = yaml.safe_load((root / path).read_text())["items"]
            for ref in refs:
                row = next(i for i in items if str(i["ref"]) == ref)
                self.assertEqual(row["status"], "covered", f"{path} {ref}")
                for cited in row["trazo"]["questions"]:
                    self.assertIn(cited, keys, f"{path} {ref}")
