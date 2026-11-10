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
    """G6.2 names G9.0 and states it as it stands (review of back #368)."""

    COMPLETE = {
        "uses_pest_control_company": False,
        "pest_control_records": ["sighting_logs"],
        "preventive_practices": ["sanitation"],
        "mechanical_controls": ["traps"],
        "material_tier": "none",
    }

    def page(self, g9=None):
        modules = {"g6_2_storage": self.answered({"storage_pest_control_materials_used": False})}
        if g9 is not None:
            modules["g9_0_facility_pest"] = g9
        return _text(generate_module_pdf(self.plan(modules), "g6_2_storage"))

    def test_an_untouched_g9_0_is_said_to_be_not_answered(self):
        page = self.page()
        self.assertIn("is asked in G9.0 Facility Pest Management; it is not answered yet.", page)
        self.assertNotIn("is answered in", page)

    def test_a_complete_g9_0_is_named_without_a_caveat(self):
        from certifications.osp_modules.conditions import missing_required

        self.assertEqual(missing_required(G9, self.COMPLETE), [], "the fixture must complete G9.0")
        self.assertIn("is asked in G9.0 Facility Pest Management.", self.page(self.answered(self.COMPLETE)))

    def test_open_required_questions_are_counted(self):
        partial = {k: v for k, v in self.COMPLETE.items() if k != "material_tier"}
        self.assertIn("1 required question there is not answered yet.", self.page(self.answered(partial)))

    def test_it_says_so_when_g9_0_is_not_applicable(self):
        page = self.page({"answers": {}, "not_applicable": True})
        self.assertIn("which the operation marks not applicable.", page)

    def test_a_standalone_page_names_no_packet_path(self):
        self.assertNotIn("modules/G9_0.pdf", self.page())

    def test_inside_a_packet_the_path_is_named(self):
        import zipfile

        from certifications.services.osp_module_pdf import generate_osp_packet

        osp = self.plan(
            {
                "g6_2_storage": self.answered({"storage_pest_control_materials_used": False}),
                "g9_0_facility_pest": self.answered(self.COMPLETE),
            }
        )
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        self.assertIn("modules/G9_0.pdf", packet.namelist())
        self.assertIn(
            "is asked in G9.0 Facility Pest Management (modules/G9_0.pdf).", _text(packet.read("modules/G6_2.pdf"))
        )


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
