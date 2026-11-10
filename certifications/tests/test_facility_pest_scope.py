"""Facility pests (content 2026.12.01).

OTCO C7 7.8, WSDA AGR 2121 M and CCOF G6.2 B3 to B9 ask facility pest management. G9.0 answered most of it but not
which pests the plan covers, several prevention and mechanical options, whether controls are sufficient, whether
National List materials are, why a synthetic not on the National List is needed, or how bait stations are used. CCOF
asks all of it on the storage form, so G6.2 now prints where G9.0 answers it.
"""

import io

from django.test import SimpleTestCase, TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_questions
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment

G9 = MODULES_BY_KEY["g9_0_facility_pest"]
AT = "2026-11-10T10:00:00Z"


def _options(key):
    return {o.value: o for p in G9.pages for q in p.questions if q.key == key for o in q.options}


def _shown(answers):
    return {q.key for _p, q in visible_questions(G9, answers)}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class OptionsTests(SimpleTestCase):
    def test_the_agents_options_are_there(self):
        self.assertTrue({"rats", "mice", "spiders", "birds"} <= set(_options("facility_pest_problems")))
        self.assertTrue(_options("facility_pest_problems")["none"].exclusive)
        self.assertTrue(
            {"incoming_inspection", "sealed_screened_openings", "positive_air_pressure", "exterior_sheet_metal"}
            <= set(_options("preventive_practices"))
        )
        self.assertTrue({"electrocutors", "sticky_traps"} <= set(_options("mechanical_controls")))
        self.assertTrue({"stored_away_from_organic", "separate_equipment"} <= set(_options("contamination_prevention")))
        self.assertTrue(_options("bait_station_use")["none"].exclusive)


class GateTests(SimpleTestCase):
    def test_follow_ups_open_on_their_answers(self):
        self.assertIn("additional_pest_measures", _shown({"pest_controls_sufficient": "no"}))
        self.assertNotIn("additional_pest_measures", _shown({"pest_controls_sufficient": "yes"}))
        self.assertNotIn("national_list_sufficient", _shown({"material_tier": "none"}))
        self.assertIn("national_list_sufficient", _shown({"material_tier": "national_list"}))
        synthetic = _shown({"material_tier": "synthetic_approved"})
        self.assertTrue({"synthetic_material_justification", "synthetic_material_justification_upload"} <= synthetic)
        self.assertNotIn("synthetic_material_justification", _shown({"material_tier": "national_list"}))


class _Plan(TestCase):
    def plan(self, modules):
        est = Establishment.objects.create(name="Cold Store", company=Company.objects.create(name="Cold"))
        return OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": modules},
        )

    @staticmethod
    def answered(answers):
        return {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}


class StoragePointerTests(_Plan):
    def test_g6_2_names_g9_0_as_where_pest_management_is_answered(self):
        osp = self.plan({"g6_2_storage": self.answered({"storage_pest_control_materials_used": False})})
        page = _text(generate_module_pdf(osp, "g6_2_storage"))
        self.assertIn("is answered in G9.0 Facility Pest Management (modules/G9_0.pdf).", page)

    def test_it_says_so_when_g9_0_is_not_applicable(self):
        osp = self.plan(
            {
                "g6_2_storage": self.answered({"storage_pest_control_materials_used": False}),
                "g9_0_facility_pest": {"answers": {}, "not_applicable": True},
            }
        )
        self.assertIn("which the operation marks not applicable.", _text(generate_module_pdf(osp, "g6_2_storage")))


class RegisterRowsTests(SimpleTestCase):
    def test_the_rows_are_covered(self):
        for agent, code, refs in (
            ("otco", "C7", ("7.8-1", "7.8-2", "7.8-3", "7.8-4", "7.8-4a", "7.8-4b")),
            ("wsda", "M", ("2", "4", "5", "6", "7")),
            ("ccof", "G6.2", ("B3", "B4", "B5", "B6", "B7", "B8", "B9")),
        ):
            form = next(
                f
                for f in load_forms(agent)
                if code in (f.code, f.document_id) or f.path.stem.startswith(f"2121-{code}-")
            )
            for ref in refs:
                self.assertEqual(next(i for i in form.items if i.ref == ref).status, "covered", (agent, ref))
