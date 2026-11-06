"""Roads, drift risk and streams beside the organic land (2026-11-06).

OTCO C9 (2024 docx) 9.3-1 "Is there any risk of drift of prohibited materials from neighboring
non-organic producers onto your organic land?" and 9.3-3 "Is your organic land bordered by a public
road(s)? ... 'No spray' signs / Notification of county/city/state / Agreements with roadside
managers / Other". CCOF ORGB40 G6.0 A2 "None, no surrounding use of prohibited materials", "Written
agreement with agency managing weed control along roadways", "List program", "My operation manages
the adjacent non-organic land and takes precautions to avoid drift (describe)". WSDA AGR 2121 §E 16
"Are streams, shorelines, gullies, or irrigation channels ... on or adjacent to sites...?".
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_compiler import compile_module_contributions
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from product.models import Parcel

AT = "2026-11-06T12:00:00Z"
OTCO = "Oregon Tilth Certified Organic (OTCO)"
WSDA = "Washington State Department of Agriculture (WSDA)"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Plan(TestCase):
    def plan(self, certifier=OTCO, g6_0=None, g4_2=None):
        est = Establishment.objects.create(
            name="Road Farm", company=Company.objects.create(name="Road Farm LLC"), state="OR"
        )
        modules = {}
        for key, answers in (("g6_0_production", g6_0), ("g4_2_natural_resources", g4_2)):
            if answers is not None:
                modules[key] = {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}
        return OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            certifier_name=certifier,
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": modules},
        )

    def row(self, osp, agent, document_id, ref):
        form = next(f for f in load_forms(agent) if f.document_id == document_id)
        return next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == ref)


class RoadsideOnTheModulePage(_Plan):
    def test_a_road_and_its_steps_print(self):
        osp = self.plan(
            g6_0={
                "borders_public_road": True,
                "roadside_management_steps": ["no_spray_signs", "agency_notification", "other"],
                "roadside_management_steps_other": "Mow the county strip ourselves each May",
            }
        )
        page = _text(generate_module_pdf(osp, "g6_0_production"))
        self.assertIn("Is your organic land bordered by a public road?", page)
        self.assertIn('"No spray" signs', page)
        self.assertIn("Notification of the county, city or state", page)
        self.assertIn("Mow the county strip ourselves each May", page)

    def test_steps_typed_before_the_road_answer_changed_do_not_print(self):
        osp = self.plan(g6_0={"borders_public_road": False, "roadside_management_steps": ["no_spray_signs"]})
        self.assertNotIn('"No spray" signs', _text(generate_module_pdf(osp, "g6_0_production")))

    def test_the_managed_adjacent_option_states_a_fact_not_a_conclusion(self):
        osp = self.plan(
            g6_0={
                "drift_safeguards": ["self_managed_adjacent", "sensitive_crop_registry"],
                "self_managed_precautions": "Conventional block sprayed only at dawn with the wind away from us",
                "drift_registry_name": "DriftWatch",
            }
        )
        narrative = "\n".join(compile_module_contributions(osp).get("commingling_barriers", []))
        self.assertNotIn("no third-party spray risk", narrative)
        self.assertIn("Conventional block sprayed only at dawn with the wind away from us", narrative)
        self.assertIn("DriftWatch", narrative)


class TheRegisterReadsTheAnswers(_Plan):
    def test_otco_9_3_3_and_9_3_1(self):
        osp = self.plan(
            g6_0={
                "drift_risk_present": True,
                "drift_safeguards": ["written_notification"],
                # 9.3-1 also cites the buffer strategy and its "other": an unanswered gate leaves it open.
                "buffer_strategies": ["roads_waterways"],
                "borders_public_road": True,
                "roadside_management_steps": ["roadside_manager_agreement"],
            }
        )
        # 9.3-1's plan includes the per-parcel buffer description (OTCO's own note), so the plan
        # needs a parcel that states its adjoining land.
        Parcel.objects.create(
            name="Home Block",
            establishment=osp.establishment,
            area=5.0,
            application_answers={"no_adjoining_prohibited": True},
        )
        self.assertEqual(self.row(osp, "otco", "C9", "9.3-3").state, "answered")
        row = self.row(osp, "otco", "C9", "9.3-1")
        self.assertEqual(row.state, "answered", row.parts)

    def test_otco_9_3_3_is_open_until_the_road_is_answered(self):
        osp = self.plan(g6_0={})
        self.assertNotIn(self.row(osp, "otco", "C9", "9.3-3").state, ("answered", "not_applicable"))

    def test_wsda_e16_streams(self):
        osp = self.plan(certifier=WSDA, g4_2={"streams_or_channels_adjacent": False})
        form = next(f for f in load_forms("wsda") if "Biodiversity" in (f.title or "") or f.code == "E")
        row = next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == "16")
        self.assertEqual(row.state, "answered")
        self.assertIn(
            "Are streams, shorelines, gullies or irrigation channels",
            _text(generate_module_pdf(osp, "g4_2_natural_resources")),
        )


class NothingNewIsRequired(TestCase):
    def test_a_module_answered_before_stays_answered(self):
        # A new required question would reopen every finished G6.0 and G4.2 module mid-renewal.
        from certifications.osp_modules import MODULE_REGISTRY

        modules = {m.key: m for m in MODULE_REGISTRY}

        new = {
            "g6_0_production": (
                "drift_risk_present",
                "drift_registry_name",
                "self_managed_precautions",
                "borders_public_road",
                "roadside_management_steps",
                "roadside_management_steps_other",
            ),
            "g4_2_natural_resources": ("streams_or_channels_adjacent",),
        }
        for module_key, keys in new.items():
            questions = {q.key: q for page in modules[module_key].pages for q in page.questions}
            for key in keys:
                self.assertIs(questions[key].required, False, f"{module_key}.{key}")
