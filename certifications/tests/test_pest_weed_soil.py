"""Pest, weed and soil questions across CCOF, OTCO and WSDA (content 2026.12.19).

G5.0 now asks the pests and diseases faced, named (OTCO C5 5.1-1, suggested from the pest records), the kinds of crop
pest managed (WSDA AGR 2121 G 3), the disease or seed a burn targets (CCOF G5.0 C3, OTCO C5 5.2-2), the plastic mulch's
material against § 205.601(b)(2) and its condition in a perennial planting (WSDA F 4, 5a), and the records of
preventive pest and weed management (G 5, F 6), with the weed section's notes (F 7). G4.0 adds OTCO C4 4.2-2's
practices in lieu of rotation, a description for perennial or container crops and site-specific notes (CCOF G4.0
A1b, A1c), and lists contour farming apart from terraces, with bare ground and other (CCOF C1, OTCO 4.1-2).

Every new question is optional, so plans already finished stay finished. The merged "contour farming or terraces"
option is retired: a stored answer prints as given, and an answer of only it is asked again.
"""

import io
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

import yaml

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import missing_required, visible_questions
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.osp_prefill import resolve_suggestions
from company.models import Company, Establishment
from history.models import PestManagementEvent, Production
from product.models import Parcel

G4 = MODULES_BY_KEY["g4_0_rotation_soil"]
G5 = MODULES_BY_KEY["g5_0_pest"]
NEW_G5 = {
    "pests_diseases_of_concern",
    "pest_taxa_managed",
    "pest_prevention_records",
    "burn_target_detail",
    "plastic_mulch_material",
    "plastic_mulch_perennial_condition",
    "weed_prevention_records",
    "weed_management_additional_notes",
}
NEW_G4 = {"in_lieu_description", "rotation_site_specific_notes"}


def _visible(module, answers) -> set:
    return {q.key for _page, q in visible_questions(module, answers)}


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class TheQuestionsOpenWhereTheFormsAskThem(SimpleTestCase):
    def test_the_burn_target_is_asked_for_disease_or_seed_and_not_for_another_reason(self):
        self.assertIn(
            "burn_target_detail", _visible(G5, {"burns_crop_residue": True, "burn_reason": ["seed_germination"]})
        )
        self.assertNotIn("burn_target_detail", _visible(G5, {"burns_crop_residue": True, "burn_reason": ["other"]}))

    def test_the_plastic_questions_open_only_with_plastic(self):
        self.assertNotIn("plastic_mulch_material", _visible(G5, {"plastic_mulch_used": False}))
        with_plastic = _visible(G5, {"plastic_mulch_used": True})
        self.assertIn("plastic_mulch_material", with_plastic)
        self.assertIn("plastic_mulch_perennial_condition", with_plastic)

    def test_container_crops_are_asked_the_in_lieu_description_and_annual_crops_are_not(self):
        self.assertIn("in_lieu_description", _visible(G4, {"system_type": ["container"]}))
        self.assertNotIn("in_lieu_practices", _visible(G4, {"system_type": ["container"]}))
        self.assertNotIn("in_lieu_description", _visible(G4, {"system_type": ["annual"]}))

    def test_no_new_question_reopens_a_finished_plan(self):
        g5 = set(
            missing_required(
                G5, {"plastic_mulch_used": True, "burns_crop_residue": True, "burn_reason": ["disease_suppression"]}
            )
        )
        self.assertEqual(g5 & NEW_G5, set())
        g4 = set(missing_required(G4, {"system_type": ["perennial", "container"]}))
        self.assertEqual(g4 & NEW_G4, set())

    def test_the_merged_erosion_option_alone_is_asked_again_and_beside_a_current_one_is_an_answer(self):
        self.assertIn("erosion_practices", missing_required(G4, {"erosion_practices": ["contour"]}))
        self.assertNotIn("erosion_practices", missing_required(G4, {"erosion_practices": ["contour", "terraces"]}))

    def test_terraces_and_contour_farming_are_separate_options(self):
        erosion = next(q for page in G4.pages for q in page.questions if q.key == "erosion_practices")
        current = {o.value for o in erosion.options if not o.retired}
        self.assertTrue({"contour_farming", "terraces", "minimize_bare_ground", "other"} <= current)
        self.assertNotIn("contour", current)


class _Farm(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Hood River Bench LLC")
        self.est = Establishment.objects.create(name="Hood River Bench", company=company, state="OR")
        parcel = Parcel.objects.create(name="Pear Block", establishment=self.est, area=9.0)
        self.history = Production.objects.create(name="Pears 2026", start_date=timezone.now(), parcel=parcel)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def _store(self, module_key, **answers):
        responses = self.osp.module_responses or {"schema_version": 1, "modules": {}}
        responses.setdefault("modules", {})[module_key] = {
            "answers": {k: {"at": "2026-11-18T10:00:00Z", "value": v} for k, v in answers.items()}
        }
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

    def _pdf(self, module_key):
        return _pdf_text(generate_module_pdf(self.osp, module_key))


class TheModulePdfsPrintTheAnswers(_Farm):
    def test_pvc_plastic_prints_a_review_line_and_the_pests_print(self):
        self._store(
            "g5_0_pest",
            pests_diseases_of_concern="Codling moth; fire blight; pear psylla",
            pest_taxa_managed=["insects", "rodents"],
            plastic_mulch_used=True,
            plastic_mulch_material="pvc",
        )
        text = self._pdf("g5_0_pest")
        self.assertIn("Codling moth; fire blight; pear psylla", text)
        self.assertIn("Insects; Rodents", text)
        self.assertIn(
            "[REVIEW] The plan says the plastic mulch is PVC; § 205.601(b)(2)(ii) allows petroleum-based plastic "
            "mulch other than polyvinyl chloride.",
            text,
        )

    def test_a_stored_merged_erosion_answer_prints_as_it_was_given(self):
        self._store("g4_0_rotation_soil", erosion_practices=["contour", "windbreaks"])
        self.assertIn("Contour farming or terraces", self._pdf("g4_0_rotation_soil"))


class ThePestRecordsSuggestTheList(_Farm):
    def _pest(self, species, day):
        return PestManagementEvent.objects.create(
            history=self.history,
            date=timezone.make_aware(timezone.datetime(2026, 5, day, 9, 0)),
            type="SC",
            pest_species=species,
        )

    def test_the_names_on_the_records_are_suggested_once_each_first_written_first(self):
        self._pest("Codling moth", 3)
        self._pest("Pear psylla", 10)
        self._pest("codling  moth", 17)
        self._pest("Pear psylla; Fire blight", 24)
        suggestion = resolve_suggestions(G5, self.est, osp=self.osp).get("pests_diseases_of_concern")
        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion["value"], "Codling moth; Pear psylla; Fire blight")
        self.assertEqual(suggestion["basis"], "named on 4 pest records")

    def test_no_pest_record_suggests_nothing(self):
        self.assertNotIn("pests_diseases_of_concern", resolve_suggestions(G5, self.est, osp=self.osp))


class TheRegisterRowsAreClosed(SimpleTestCase):
    ROWS = {
        "ccof/forms/G4.0-rotation-soil.yaml": ("A1b", "A1c", "C1"),
        "ccof/forms/G5.0-pest-management.yaml": ("C3",),
        "otco/forms/C4-soil-crop-fertility-management.yaml": ("4.1-2", "4.2-2"),
        "otco/forms/C5-pest-disease-weed-management.yaml": ("5.1-1", "5.2-2"),
        "wsda/forms/2121-F-weed.yaml": ("4", "5a", "6", "7"),
        "wsda/forms/2121-G-pest.yaml": ("3", "5"),
    }

    def test_every_row_is_covered_and_cites_questions_that_exist(self):
        root = Path(__file__).resolve().parents[2] / "documentation/compliance/certifiers"
        keys = {f"{m.key}.{q.key}" for m in (G4, G5) for page in m.pages for q in page.questions}
        for path, refs in self.ROWS.items():
            items = yaml.safe_load((root / path).read_text())["items"]
            for ref in refs:
                row = next(i for i in items if str(i["ref"]) == ref)
                self.assertEqual(row["status"], "covered", f"{path} {ref}")
                for cited in row["trazo"]["questions"]:
                    self.assertIn(cited, keys, f"{path} {ref}")


class TheGoldenCasesAreNotShadowed(SimpleTestCase):
    """Review of back #479: a second "g5_0_pest" key in GOLDEN_ANSWER_CASES silently dropped the nine cases above it,
    because a dict literal keeps only the last of a duplicate key. Read from the source, where the duplicate is."""

    def test_no_module_and_no_case_name_appears_twice(self):
        import ast
        from collections import Counter

        path = Path(__file__).resolve().parents[1] / "management/commands/export_osp_module_fixture.py"
        tree = ast.parse(path.read_text())
        cases = next(
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "GOLDEN_ANSWER_CASES" for t in n.targets)
        )
        dicts = [("GOLDEN_ANSWER_CASES", cases)] + [
            (k.value, v) for k, v in zip(cases.keys, cases.values) if isinstance(v, ast.Dict)
        ]
        for name, node in dicts:
            counts = Counter(k.value for k in node.keys if isinstance(k, ast.Constant))
            self.assertEqual([k for k, c in counts.items() if c > 1], [], name)
